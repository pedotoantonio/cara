"""Parse the dietista PDFs and seed the diet catalog (idempotent).

Run inside the backend container:

    docker exec cara-backend python -m cara.diet.seed

Optional env / args:
    CARA_DIET_PDF_DIR     dir holding the 2 source PDFs (default /app/uploads/diet)
    CARA_DIET_USER_EMAIL  owner of the plan (default pedotoa@gmail.com — Antonio)

What it does (re-runnable, no duplicates):
  1. Locate the two source PDFs, parse them with pypdf for *traceability*
     (assert known anchor strings are present → guards against the wrong
     file being seeded) and compute a sha256 `version` of the PDF set.
  2. Copy the PDFs into local storage and create/activate a `DietPlan`
     row keyed by (user_id, version). A new plan PDF bumps the version
     (new active plan, previous one deactivated); the same PDFs are a no-op.
  3. Upsert `food_items` (by name), `diet_rules` (by plan_id+category) and
     `recipes` (by name) from `cara.diet.catalog` — the faithful PDF
     transcription. season_months/kcal are external enrichment (marked).

PDF parsing is best-effort: if a file is missing we still seed the
catalog (with a warning) so the module is usable in dev without the PDFs.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cara.config import settings
from cara.diet.catalog import DIET_RULES, FOOD_ITEMS, RECIPES
from cara.models.diet import DietPlan, DietRule, FoodItem, Recipe
from cara.models.user import User

log = structlog.get_logger(__name__)

PDF_DIR = Path(os.environ.get("CARA_DIET_PDF_DIR", "/app/uploads/diet"))
USER_EMAIL = os.environ.get("CARA_DIET_USER_EMAIL", "pedotoa@gmail.com")
PLAN_NAME = "Piano alimentare Antonio Pedoto — Dott.ssa Elena Poletti"

# Source PDFs + an anchor string that MUST appear in each (traceability:
# guards against seeding from the wrong document). Filenames are matched
# loosely (spaces or underscores).
SOURCES = [
    ("indicazioni generali", "INDICAZIONI GENERALI"),
    ("piano alimentare", "PIANO ALIMENTARE"),
]


# ─── PDF traceability ──────────────────────────────────────────────


def _find_pdf(stem_hint: str) -> Path | None:
    if not PDF_DIR.is_dir():
        return None
    norm = stem_hint.replace(" ", "").replace("_", "").lower()
    for p in PDF_DIR.glob("*.pdf"):
        if norm in p.stem.replace(" ", "").replace("_", "").lower():
            return p
    return None


def _verify_and_hash() -> tuple[str, list[Path]]:
    """Parse each PDF, assert its anchor string, return (version, paths).

    version = sha256(concatenated file bytes)[:16]; stable for the same
    PDFs, changes when the plan is updated.
    """
    hasher = hashlib.sha256()
    found: list[Path] = []
    for hint, anchor in SOURCES:
        path = _find_pdf(hint)
        if path is None:
            log.warning("diet.seed.pdf_missing", hint=hint, dir=str(PDF_DIR))
            continue
        blob = path.read_bytes()
        hasher.update(blob)
        found.append(path)
        try:
            from pypdf import PdfReader  # noqa: PLC0415

            import io

            text = "\n".join(
                (pg.extract_text() or "") for pg in PdfReader(io.BytesIO(blob)).pages
            )
            if anchor.lower() not in text.lower():
                log.warning(
                    "diet.seed.anchor_missing", path=str(path), anchor=anchor
                )
            else:
                log.info("diet.seed.pdf_verified", path=str(path), pages=text.count("\n"))
        except Exception as exc:  # noqa: BLE001
            log.warning("diet.seed.pdf_parse_failed", path=str(path), error=str(exc))

    version = hasher.hexdigest()[:16] if found else "catalog-only"
    return version, found


def _store_sources(found: list[Path]) -> str | None:
    """Copy source PDFs into local storage; return the storage dir path."""
    if not found:
        return None
    # Storage = /app/uploads/diet (host ./data/uploads/diet via compose mount),
    # the same uploads root used by cara.services.files.
    dest_dir = Path("/app/uploads/diet")
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        for p in found:
            target = dest_dir / p.name
            if p.resolve() != target.resolve():
                shutil.copy2(p, target)
        return str(dest_dir)
    except Exception as exc:  # noqa: BLE001
        log.warning("diet.seed.store_failed", error=str(exc))
        return str(found[0].parent)


# ─── Upserts ───────────────────────────────────────────────────────


async def _upsert_plan(session: AsyncSession, version: str, src_path: str | None) -> DietPlan | None:
    user = (
        await session.execute(select(User).where(User.email == USER_EMAIL))
    ).scalar_one_or_none()
    if user is None:
        log.warning("diet.seed.user_missing", email=USER_EMAIL)
        return None

    existing = (
        await session.execute(
            select(DietPlan).where(DietPlan.user_id == user.id)
        )
    ).scalars().all()

    current = next((p for p in existing if p.version == version), None)
    if current is None:
        # New plan version → deactivate the others, insert active.
        for p in existing:
            p.active = False
        current = DietPlan(
            user_id=user.id,
            name=PLAN_NAME,
            version=version,
            active=True,
            source_document_path=src_path,
        )
        session.add(current)
        await session.flush()  # need the id for rules
        log.info("diet.seed.plan_created", user_id=user.id, version=version)
    else:
        current.active = True
        current.source_document_path = src_path or current.source_document_path
        for p in existing:
            if p.id != current.id:
                p.active = False
    return current


async def _upsert_food_items(session: AsyncSession) -> tuple[int, int]:
    existing = {
        row.name: row
        for row in (await session.execute(select(FoodItem))).scalars()
    }
    ins = upd = 0
    cols = (
        "status", "protein_category", "food_group", "default_portion_g",
        "portion_primo_g", "portion_secondo_g", "kcal_per_100g",
        "season_months", "notes",
    )
    for item in FOOD_ITEMS:
        row = existing.get(item["name"])
        if row is None:
            session.add(FoodItem(**item))
            ins += 1
        else:
            changed = False
            for c in cols:
                if getattr(row, c) != item.get(c):
                    setattr(row, c, item.get(c))
                    changed = True
            upd += int(changed)
    return ins, upd


async def _upsert_rules(session: AsyncSession, plan_id: int) -> tuple[int, int]:
    existing = {
        row.category: row
        for row in (
            await session.execute(select(DietRule).where(DietRule.plan_id == plan_id))
        ).scalars()
    }
    ins = upd = 0
    cols = (
        "target_min", "target_max", "period", "portion_primo_g",
        "portion_secondo_g", "portion_note", "kcal_estimate",
    )
    for rule in DIET_RULES:
        row = existing.get(rule["category"])
        if row is None:
            session.add(DietRule(plan_id=plan_id, **rule))
            ins += 1
        else:
            changed = False
            for c in cols:
                if getattr(row, c) != rule.get(c):
                    setattr(row, c, rule.get(c))
                    changed = True
            upd += int(changed)
    return ins, upd


async def _upsert_recipes(session: AsyncSession) -> tuple[int, int]:
    existing = {
        row.name: row
        for row in (await session.execute(select(Recipe))).scalars()
    }
    ins = upd = 0
    for rec in RECIPES:
        row = existing.get(rec["name"])
        if row is None:
            session.add(Recipe(**rec))
            ins += 1
        else:
            changed = False
            for c in ("ingredients", "steps", "source"):
                if getattr(row, c) != rec.get(c):
                    setattr(row, c, rec.get(c))
                    changed = True
            upd += int(changed)
    return ins, upd


async def seed(session: AsyncSession) -> dict[str, object]:
    version, found = _verify_and_hash()
    src_path = _store_sources(found)

    plan = await _upsert_plan(session, version, src_path)
    f_ins, f_upd = await _upsert_food_items(session)
    r_ins = r_upd = 0
    if plan is not None:
        r_ins, r_upd = await _upsert_rules(session, plan.id)
    rec_ins, rec_upd = await _upsert_recipes(session)

    await session.commit()
    return {
        "version": version,
        "plan": None if plan is None else {"id": plan.id, "active": plan.active},
        "food_items": {"inserted": f_ins, "updated": f_upd, "total": len(FOOD_ITEMS)},
        "diet_rules": {"inserted": r_ins, "updated": r_upd, "total": len(DIET_RULES)},
        "recipes": {"inserted": rec_ins, "updated": rec_upd, "total": len(RECIPES)},
    }


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        result = await seed(session)
    await engine.dispose()
    print("diet seed:", result)


if __name__ == "__main__":
    asyncio.run(main())
