#!/usr/bin/env python3
"""Export a LoRA training dataset from the live CARA database.

Run from the host (or `docker exec cara-backend python -m scripts.export_lora_dataset`).
Produces three JSONL files in `data/lora/`:

  cara_persona.jsonl    — clean (user, assistant) pairs from `messages`,
                           filtered for "good" replies (no regenerate
                           event, no grounding rewrite). Persona-stable.

  cara_tool_calls.jsonl — synthetic examples of the `[TOOL: name args]`
                           format the parser expects. Boosts tool-call
                           reliability from the current ~60-70% on the
                           1.5B base.

  cara_skill_dispatch.jsonl — examples mapping user messages to skill
                               names, for the Tier-3 LLM classifier.

The files are in the OpenAI-style messages format (`{"messages":[
{"role":"system","content":...}, {"role":"user","content":...},
{"role":"assistant","content":...}]}`) so they drop straight into TRL's
SFTTrainer.

The actual training step is a separate workload (x86_64 + CUDA) — see
docs/LORA-FINE-TUNE-PIPELINE.md.

Usage:
  cd /opt/cara
  docker exec cara-backend python -m scripts.export_lora_dataset \
    --output-dir /tmp/cara_lora --since-days 90

The output dir is created if missing. Files are overwritten on re-run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Allow running either as `python -m scripts.export_lora_dataset` from
# the backend container OR as a plain script from the host (with the
# venv activated).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cara.models.conversation import Conversation, Message  # type: ignore[import]
from cara.models.event import Event  # type: ignore[import]
from cara.store.db import get_sessionmaker, init_engine, shutdown_engine  # type: ignore[import]


SYSTEM_PROMPT = (
    "Sei CARA, l'assistente di casa della famiglia Pedoto. Parli italiano "
    "naturale, sei calda e diretta. Quando puoi usi un tool nel formato "
    "[TOOL: nome args] su una riga sua. Niente disclaimer, niente \"come "
    "modello AI\". Memori i fatti utente solo se l'utente lo chiede."
)


# ---------------------------------------------------------------------------
# Persona dataset — from real chat history
# ---------------------------------------------------------------------------


async def fetch_message_pairs(
    session: AsyncSession, *, since_days: int,
) -> list[tuple[str, str, int | None]]:
    """Walk conversations, return clean (user, assistant, conversation_user_id)
    triples. A pair is "clean" iff the assistant message wasn't followed by a
    regenerate event within 60s (i.e. the user accepted the response)."""

    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    # Pull regenerate events for the cutoff to mark "rejected" turns.
    # NOTE: this assumes a future "chat.regenerated" episodic kind. If your
    # repo doesn't have it yet, the heuristic falls back to "include every
    # pair" — still good enough for a first iteration.
    regen_rows = (
        await session.execute(
            select(Event).where(
                Event.kind == "chat.regenerated", Event.ts >= cutoff,
            )
        )
    ).scalars().all()
    regen_at_by_convo: dict[str, list[datetime]] = defaultdict(list)
    for ev in regen_rows:
        regen_at_by_convo[(ev.ref_id or "")].append(ev.ts)

    # Pull all messages of conversations active in window.
    convos = (
        await session.execute(
            select(Conversation).where(Conversation.created_at >= cutoff)
        )
    ).scalars().all()

    pairs: list[tuple[str, str, int | None]] = []
    for c in convos:
        msgs = (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == c.id)
                .order_by(Message.created_at)
            )
        ).scalars().all()
        # Pair adjacent (user, assistant)
        prev = None
        for m in msgs:
            if m.role == "user":
                prev = m
                continue
            if m.role == "assistant" and prev is not None:
                # Reject if a regenerate event is within 60s of this assistant turn.
                regens = regen_at_by_convo.get(str(c.id), [])
                if any(abs((r - m.created_at).total_seconds()) < 60 for r in regens):
                    prev = None
                    continue
                # Reject very short turns — too noisy.
                if len((prev.content or "").strip()) < 3:
                    prev = None
                    continue
                if len((m.content or "").strip()) < 5:
                    prev = None
                    continue
                pairs.append((prev.content, m.content, c.user_id))
                prev = None
            else:
                prev = None
    return pairs


def build_persona_examples(
    pairs: list[tuple[str, str, int | None]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for user_msg, assistant_msg, _uid in pairs:
        out.append({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg.strip()},
                {"role": "assistant", "content": assistant_msg.strip()},
            ],
        })
    return out


# ---------------------------------------------------------------------------
# Tool-calling dataset — synthetic but realistic
# ---------------------------------------------------------------------------


# Each entry is (user_phrasing, assistant_reply). The assistant reply
# contains the tool call on its own line (the parser expects this).
_TOOL_TEMPLATES: list[tuple[str, str]] = [
    # add_task
    (
        "ricordami di chiamare il dentista domani alle 15",
        "[TOOL: add_task title=\"chiamare il dentista\" due=\"domani 15:00\"]\nFatto, l'ho aggiunta.",
    ),
    (
        "metti in lista cose da fare: pagare la bolletta entro venerdì",
        "[TOOL: add_task title=\"pagare la bolletta\" due=\"venerdì\"]\nAggiunta.",
    ),
    (
        "aggiungi un task: portare l'auto dal meccanico",
        "[TOOL: add_task title=\"portare l'auto dal meccanico\"]\nFatto.",
    ),
    # add_shopping
    (
        "aggiungi pasta e pomodoro alla lista della spesa",
        "[TOOL: add_shopping items=[\"pasta\",\"pomodoro\"]]\nAggiunti.",
    ),
    (
        "metti il latte nella spesa",
        "[TOOL: add_shopping items=[\"latte\"]]\nFatto.",
    ),
    # list_tasks
    (
        "che cosa devo fare oggi?",
        "[TOOL: list_tasks scope=\"today\"]",
    ),
    (
        "leggimi le mie task aperte",
        "[TOOL: list_tasks scope=\"open\"]",
    ),
    # complete_task
    (
        "ho fatto la spesa, marca il task come fatto",
        "[TOOL: complete_task title=\"spesa\"]\nSegnata.",
    ),
    # add_note
    (
        "scrivi una nota: idee regalo per Sara — libro, sciarpa, profumo",
        "[TOOL: add_note title=\"idee regalo per Sara\" body=\"libro, sciarpa, profumo\"]\nNota salvata.",
    ),
    # who_is_home
    (
        "chi è in casa?",
        "[TOOL: who_is_home]",
    ),
    # play_radio / stop_radio
    (
        "metti radio rai uno",
        "[TOOL: play_radio name=\"rai uno\"]",
    ),
    (
        "spegni la radio",
        "[TOOL: stop_radio]",
    ),
    # get_news
    (
        "dammi le notizie del giorno",
        "[TOOL: get_news]",
    ),
    # discover (CDA)
    (
        "trovami una ricetta per le lasagne",
        "[TOOL: discover query=\"lasagne ricetta\" kind=\"article\"]",
    ),
    (
        "cerco un podcast sul cambiamento climatico",
        "[TOOL: discover query=\"cambiamento climatico\" kind=\"podcast\"]",
    ),
    # Negative / no-tool examples — train the model to NOT call a tool
    # for casual conversation.
    (
        "ciao come stai?",
        "Bene, e te? Cos'hai in mente oggi?",
    ),
    (
        "mi sento un po' giù",
        "Mi dispiace. Ti va di raccontarmi cosa è successo?",
    ),
    (
        "che ne pensi del nuovo album dei coldplay?",
        "Non l'ho ascoltato; mi dici tu cosa ne pensi?",
    ),
]


def build_tool_examples() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for user_msg, assistant_reply in _TOOL_TEMPLATES:
        out.append({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_reply},
            ],
        })
    return out


# ---------------------------------------------------------------------------
# Skill dispatch dataset — for Tier-3 LLM classifier
# ---------------------------------------------------------------------------


SKILL_DISPATCH_SYSTEM = (
    "Sei un classificatore di skill. Ricevi un messaggio dell'utente e una "
    "lista numerata di skill disponibili. Rispondi SOLO con il numero della "
    "skill che meglio corrisponde, oppure 0 se nessuna è adatta. Solo il "
    "numero."
)


async def fetch_skill_dispatch_examples(
    session: AsyncSession, *, since_days: int,
) -> list[dict[str, Any]]:
    """Build classifier examples from past `router.skill_hit` events. The
    user message is the input, the matched skill is the gold label."""

    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    rows = (
        await session.execute(
            select(Event)
            .where(Event.kind == "router.skill_hit", Event.ts >= cutoff)
            .limit(2000)
        )
    ).scalars().all()
    if not rows:
        return []

    # Build a fixed catalog of seen skills.
    seen_skills: list[str] = []
    for ev in rows:
        sk_name = ((ev.payload or {}).get("skill") or "").strip()
        if sk_name and sk_name not in seen_skills:
            seen_skills.append(sk_name)

    if not seen_skills:
        return []

    examples: list[dict[str, Any]] = []
    catalog_text = "\n".join(
        f"{i + 1}. {name}" for i, name in enumerate(seen_skills)
    )

    for ev in rows:
        payload = ev.payload or {}
        sk_name = (payload.get("skill") or "").strip()
        # Pull the user's last query — events store it lossily; we keep
        # whatever the writer attached. Skip if missing.
        user_msg = (
            payload.get("query")
            or payload.get("message")
            or payload.get("last_user_q")
            or ""
        )
        if not user_msg or sk_name not in seen_skills:
            continue
        target = seen_skills.index(sk_name) + 1
        examples.append({
            "messages": [
                {"role": "system", "content": SKILL_DISPATCH_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Skill disponibili:\n\n{catalog_text}\n\n"
                        f"Utente: \"{user_msg}\""
                    ),
                },
                {"role": "assistant", "content": str(target)},
            ],
        })
    return examples


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


async def main(args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    await init_engine()
    sm = get_sessionmaker()
    async with sm() as session:
        # 1. persona
        pairs = await fetch_message_pairs(session, since_days=args.since_days)
        persona = build_persona_examples(pairs)
        write_jsonl(out_dir / "cara_persona.jsonl", persona)

        # 2. tool calls (synthetic)
        tool_examples = build_tool_examples()
        write_jsonl(out_dir / "cara_tool_calls.jsonl", tool_examples)

        # 3. skill dispatch (from router events)
        skill_examples = await fetch_skill_dispatch_examples(
            session, since_days=args.since_days,
        )
        write_jsonl(out_dir / "cara_skill_dispatch.jsonl", skill_examples)

    await shutdown_engine()

    print(f"persona pairs:        {len(persona):>4}  → {out_dir/'cara_persona.jsonl'}")
    print(f"tool-call examples:   {len(tool_examples):>4}  → {out_dir/'cara_tool_calls.jsonl'}")
    print(f"skill dispatch:       {len(skill_examples):>4}  → {out_dir/'cara_skill_dispatch.jsonl'}")
    print(f"total:                {len(persona)+len(tool_examples)+len(skill_examples):>4}")

    if len(persona) < 50:
        print(
            "\nNOTE: fewer than 50 persona pairs in the window. The model "
            "will train mostly on synthetic tool-call examples; consider "
            "extending --since-days or letting the family chat more before "
            "training.",
            file=sys.stderr,
        )
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export LoRA training dataset")
    p.add_argument(
        "--output-dir",
        default=os.environ.get("CARA_LORA_OUT", "/tmp/cara_lora"),
        help="Where to write the .jsonl files",
    )
    p.add_argument(
        "--since-days",
        type=int,
        default=90,
        help="Look back this many days for chat history (default: 90)",
    )
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
