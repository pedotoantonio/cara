"""Workflow REST API — invoke a concrete workflow on a typed input.

  POST /api/v1/workflows/run         dispatch input through every registered
                                     workflow until one matches; returns
                                     proposed actions and auto-confirm
                                     hints. Optionally executes if
                                     `confirmed=True`.
  GET  /api/v1/workflows              list registered workflows + status
  POST /api/v1/workflows/trust/revoke revoke an auto-confirm pattern
  GET  /api/v1/workflows/trust        list user's trust streaks

The actual concrete workflow registration happens at module load
time — `_default_registry()` instantiates Receipt / Recipe / Bill
with the production adapters (OCR / shopping_svc / budgets_svc /
tasks_svc / recipe_chain). Tests build a registry with stubs.

Adapters require a sync session reach; we resolve them via lazy
`get_session` so each request gets its own session.
"""

from __future__ import annotations

import base64
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.store import get_session
from cara.workflows.auto_confirm import (
    action_signature,
    get_trust,
    list_trust,
    record_confirmed,
    record_rejected,
    revoke_trust,
)
from cara.workflows.base import (
    ProposedAction,
    WorkflowInput,
    WorkflowRegistry,
    get_default_registry,
)


router = APIRouter(prefix="/workflows", tags=["workflows"])


# ---------------------------------------------------------------------------
# Adapters wiring (production: bind to real services on demand)
# ---------------------------------------------------------------------------


def _build_workflow_registry() -> WorkflowRegistry:
    """Instantiate concrete workflows with production adapters.

    Registered ONCE per process, lazily on the first request. The
    workflow instances are stateless beyond the adapters.
    """
    reg = get_default_registry()
    if reg.list():
        return reg

    from cara.ai.ocr import OCRService
    from cara.services import recipe_chain
    from cara.services import shopping as shopping_svc
    from cara.workflows.bill import BillWorkflow
    from cara.workflows.recipe import RecipeWorkflow
    from cara.workflows.receipt import ReceiptWorkflow

    ocr = OCRService()

    # ReceiptWorkflow adapters wrap the existing service signatures.
    async def _shopping_list(user_id: int):
        # NOTE: needs a session — we close over the request session via
        # contextvar at call site. Here, fetch a fresh session.
        from cara.store.db import get_sessionmaker
        sm = get_sessionmaker()
        async with sm() as s:
            return await shopping_svc.list_items(s, user_id=user_id)

    async def _shopping_mark_bought(user_id: int, item_id: int) -> bool:
        from cara.store.db import get_sessionmaker
        sm = get_sessionmaker()
        async with sm() as s:
            updated = await shopping_svc.update_item(
                s, item_id, user_id=user_id, bought=True,
            )
            await s.commit()
            return updated is not None

    async def _add_expense(**kwargs):
        from cara.services import budgets as budget_svc
        from cara.store.db import get_sessionmaker
        sm = get_sessionmaker()
        async with sm() as s:
            return await budget_svc.add_expense(s, **kwargs, commit=True)

    async def _ocr_extract(image_bytes: bytes):
        return await ocr.extract(image_bytes)

    reg.register(ReceiptWorkflow(
        ocr_extract=_ocr_extract,
        shopping_list=_shopping_list,
        shopping_mark_bought=_shopping_mark_bought,
        add_expense=_add_expense,
    ))

    # RecipeWorkflow adapters.
    async def _add_shopping(*, user_id: int, title: str):
        from cara.store.db import get_sessionmaker
        sm = get_sessionmaker()
        async with sm() as s:
            row = await shopping_svc.create_item(s, user_id=user_id, title=title)
            await s.commit()
            return row

    # `recipe_chain` provides ingredient extraction from cleaned text.
    reg.register(RecipeWorkflow(
        fetch_text=None,                                  # URL fetch wired later
        extract_ingredients=recipe_chain.extract_ingredients,
        add_shopping=_add_shopping,
    ))

    # BillWorkflow adapters.
    def _pdf_extract(pdf_bytes: bytes) -> str:
        # pypdf wrapper — runs synchronously, fast for typical bills.
        try:
            from pypdf import PdfReader
            from io import BytesIO
            reader = PdfReader(BytesIO(pdf_bytes))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception:
            return ""

    async def _add_task(*, user_id: int, title: str, due_date):
        from cara.services import tasks as task_svc
        from cara.store.db import get_sessionmaker
        sm = get_sessionmaker()
        async with sm() as s:
            return await task_svc.create_task(
                s, user_id=user_id, title=title, due_date=due_date,
            )

    reg.register(BillWorkflow(
        pdf_extract=_pdf_extract,
        add_task=_add_task,
        add_expense=_add_expense,
    ))
    return reg


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class WorkflowRunRequest(BaseModel):
    """Input to dispatch.

    Either `image_b64` (receipt photo) or `pdf_b64` (bill) or `text`
    (recipe URL or typed message). At least one must be present.
    """

    text: str | None = Field(default=None, max_length=10_000)
    url: str | None = Field(default=None, max_length=2000)
    ocr_text: str | None = Field(default=None, max_length=20_000)
    pdf_text: str | None = Field(default=None, max_length=50_000)
    image_b64: str | None = Field(default=None, max_length=20_000_000)
    pdf_b64: str | None = Field(default=None, max_length=50_000_000)
    confirmed: bool = False


class ProposedActionOut(BaseModel):
    tool: str
    args: dict[str, Any]
    summary: str
    reversible: bool
    signature: str
    auto_confirmable: bool
    confirms_seen: int
    confirms_remaining: int


class WorkflowRunResponse(BaseModel):
    matched: bool
    workflow_name: str | None = None
    confidence: float | None = None
    reason: str | None = None
    structured: dict[str, Any] | None = None
    proposed_actions: list[ProposedActionOut] = Field(default_factory=list)
    executed: bool = False
    execution_results: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_input(req: WorkflowRunRequest, user_id: int) -> WorkflowInput:
    """Translate the REST request into a WorkflowInput, decoding base64
    payloads on the way in. Detects the kind from the most-specific
    field present (image > pdf > url > text)."""
    payload: dict[str, Any] = {"user_id": user_id}
    kind = "text"

    if req.image_b64:
        try:
            payload["image_bytes"] = base64.b64decode(req.image_b64)
        except Exception as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"image_b64 invalid: {exc}",
            ) from exc
        kind = "image"
    if req.pdf_b64:
        try:
            payload["pdf_bytes"] = base64.b64decode(req.pdf_b64)
        except Exception as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"pdf_b64 invalid: {exc}",
            ) from exc
        kind = "pdf"
    if req.ocr_text:
        payload["ocr_text"] = req.ocr_text
        if kind == "text":
            kind = "image"
    if req.pdf_text:
        payload["pdf_text"] = req.pdf_text
        if kind == "text":
            kind = "pdf"
    if req.url:
        payload["url"] = req.url
        if kind == "text":
            kind = "url"
    if req.text:
        payload["text"] = req.text

    if (
        not req.image_b64 and not req.pdf_b64 and not req.text
        and not req.url and not req.ocr_text and not req.pdf_text
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "request must include at least one of: text, url, image_b64, "
            "pdf_b64, ocr_text, pdf_text",
        )

    return WorkflowInput(kind=kind, payload=payload, user_id=user_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_workflows(
    user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    reg = _build_workflow_registry()
    return {
        "workflows": [
            {
                "name": w.name,
                "version": getattr(w, "version", "?"),
                "enabled": reg.is_enabled(w.name),
            }
            for w in reg.list()
        ],
    }


@router.post("/run", response_model=WorkflowRunResponse)
async def run_workflow(
    body: WorkflowRunRequest,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> WorkflowRunResponse:
    """Walk registered workflows in order; first match wins.

    If `confirmed=False` (default), returns proposed actions + per-action
    auto-confirm hints, lets the UI render the conferma card. If
    `confirmed=True`, executes after walking (still returns the
    structured output for audit).
    """
    reg = _build_workflow_registry()
    inp = _build_input(body, user_id=user.id)

    classify_match = await reg.classify_first_match(inp)
    if classify_match is None:
        return WorkflowRunResponse(matched=False, reason="no_match")

    workflow, classify_result = classify_match
    structured = await workflow.extract(inp, classify_result.hints or {})
    proposed = await workflow.propose(structured)

    # Decorate each proposed action with auto-confirm trust signals.
    actions_out: list[ProposedActionOut] = []
    for a in proposed:
        sig = action_signature(a)
        decision = await get_trust(
            session, user_id=user.id, workflow_kind=workflow.name, action=a,
        )
        actions_out.append(ProposedActionOut(
            tool=a.tool,
            args=a.args,
            summary=a.summary,
            reversible=a.reversible,
            signature=sig,
            auto_confirmable=decision.auto_confirmable,
            confirms_seen=decision.confirms_seen,
            confirms_remaining=decision.confirms_remaining,
        ))

    response = WorkflowRunResponse(
        matched=True,
        workflow_name=workflow.name,
        confidence=structured.confidence,
        reason=classify_result.reason,
        structured=structured.data,
        proposed_actions=actions_out,
    )

    if body.confirmed and proposed:
        results = await workflow.execute(proposed)
        response.executed = True
        response.execution_results = [
            {
                "tool": r.action.tool,
                "ok": r.ok,
                "error": r.error,
                "output": r.output,
            }
            for r in results
        ]
        # Bump the trust streak per successfully-executed action.
        for r in results:
            if r.ok:
                await record_confirmed(
                    session, user_id=user.id,
                    workflow_kind=workflow.name, action=r.action,
                    commit=True,
                )

    return response


# ---------------------------------------------------------------------------
# Trust management
# ---------------------------------------------------------------------------


class TrustOut(BaseModel):
    workflow_kind: str
    action_signature: str
    confirms_streak: int
    revoked: bool


class RevokeTrustRequest(BaseModel):
    workflow_kind: str = Field(min_length=1, max_length=40)
    signature: str = Field(min_length=1, max_length=200)


class RejectActionRequest(BaseModel):
    workflow_kind: str = Field(min_length=1, max_length=40)
    tool: str = Field(min_length=1, max_length=80)
    arg_keys: list[str] = Field(default_factory=list)


@router.get("/trust", response_model=list[TrustOut])
async def get_my_trust(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[TrustOut]:
    rows = await list_trust(session, user_id=user.id)
    return [
        TrustOut(
            workflow_kind=r.workflow_kind,
            action_signature=r.action_signature,
            confirms_streak=r.confirms_streak,
            revoked=r.revoked,
        )
        for r in rows
    ]


@router.post("/trust/revoke")
async def revoke_trust_pattern(
    body: RevokeTrustRequest,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    ok = await revoke_trust(
        session,
        user_id=user.id,
        workflow_kind=body.workflow_kind,
        signature=body.signature,
        commit=True,
    )
    if not ok:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "no trust row matches that signature",
        )
    return {"ok": True}


@router.post("/trust/reject")
async def reject_action_pattern(
    body: RejectActionRequest,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, Any]:
    """Equivalent to the user pressing 'no' on a confirm card —
    resets the streak. Useful for the UI's 'questo non l'avrei voluto'
    feedback button."""
    fake_action = ProposedAction(
        tool=body.tool,
        args={k: 0 for k in body.arg_keys},
        summary="(rejection)",
    )
    await record_rejected(
        session, user_id=user.id, workflow_kind=body.workflow_kind,
        action=fake_action, commit=True,
    )
    return {"ok": True}
