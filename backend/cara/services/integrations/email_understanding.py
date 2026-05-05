"""3-layer email NLU pipeline.

Layer 1 — Deterministic Italian regex + date parser:
    Cheap, runs every email. Looks for trigger words, dates, locations.
    Output: candidates dict.

Layer 2 — Local LLM (Qwen 1.5B) classifier:
    Runs only when Layer 1 has at least one date candidate or trigger
    word. Returns a strict JSON. ~1s per email.

Layer 3 — Cloud Haiku (opt-in):
    Runs when the user has `email_cloud_fallback_enabled=True` in admin
    AND Layer 2 confidence < 0.7.

The result is a `Proposal` dataclass that the caller persists in
`email_proposals` if `proposal_type != 'NON_RILEVANTE'`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog


log = structlog.get_logger(__name__)


# Trigger words — if NONE of these appears we skip immediately.
_TRIGGER_RE = re.compile(
    r"\b(?:promemoria|appuntamento|convocazione|scadenza|prenotazion|"
    r"consegna|visita|riunion|incontro|conferma|spedizion|"
    r"ritiro|colloqui|udienz|audizion|verbale|presentazion|"
    r"pagamento|fattura|bolletta|preavviso)\w*",
    re.IGNORECASE,
)

# Hard-skip blacklist (clear non-events).
_NEGATIVE_RE = re.compile(
    r"\b(?:newsletter|unsubscribe|cancella iscrizione|offerta\s+esclusiv|"
    r"promo\w+|sconto\w+|black\s*friday|"
    r"verifica\s+(?:il\s+)?tuo\s+indirizzo|password\s+reset|"
    r"codice\s+di\s+accesso|otp|two[-\s]?factor|"
    r"github|gitlab|google\s+(?:cloud|workspace)\s+billing)\b",
    re.IGNORECASE,
)


@dataclass
class Proposal:
    proposal_type: str           # 'appointment' | 'task' | 'bill_reminder' | 'NON_RILEVANTE'
    title: str
    due_at: datetime | None
    location: str | None
    person: str | None
    notes: str | None
    confidence: float
    source_layer: str            # 'pattern' | 'local_llm' | 'cloud_llm'

    def is_relevant(self) -> bool:
        return self.proposal_type != "NON_RILEVANTE" and self.confidence >= 0.5


# ---------------------------------------------------------------------------
# Layer 1 — deterministic
# ---------------------------------------------------------------------------


def layer1_classify(*, subject: str, body: str) -> Proposal:
    full = f"{subject}\n{body}"

    if _NEGATIVE_RE.search(full):
        return Proposal(
            proposal_type="NON_RILEVANTE", title="", due_at=None,
            location=None, person=None, notes=None,
            confidence=0.0, source_layer="pattern",
        )

    if not _TRIGGER_RE.search(full):
        return Proposal(
            proposal_type="NON_RILEVANTE", title="", due_at=None,
            location=None, person=None, notes=None,
            confidence=0.0, source_layer="pattern",
        )

    # Try the Italian date parser on (subject + first 1000 char body).
    from cara.services.it_date_parser import parse_due

    head = (subject + "\n" + body)[:2000]
    parsed = parse_due(head)
    due_at = parsed.when if parsed else None

    # Heuristic location: "presso ...", "in via ...", "a Roma ..."
    loc = None
    m = re.search(
        r"\b(?:presso|in\s+via|via\s+|piazza\s+|corso\s+|viale\s+|c\.so\s+)([A-Z][^\n,.;]{2,80})",
        full,
    )
    if m:
        loc = m.group(0)[:120].strip(" ,.;")

    # Heuristic title: subject (clamped) — refined by LLM in Layer 2.
    title = (subject or "Promemoria")[:120].strip()

    confidence = 0.55 if due_at else 0.35

    proposal_type = "appointment" if due_at else "task"
    if "fattura" in full.lower() or "bolletta" in full.lower() or "scadenza" in full.lower():
        proposal_type = "bill_reminder"
        confidence += 0.05

    return Proposal(
        proposal_type=proposal_type,
        title=title,
        due_at=due_at,
        location=loc,
        person=None,
        notes=None,
        confidence=min(0.9, confidence),
        source_layer="pattern",
    )


# ---------------------------------------------------------------------------
# Layer 2 — local LLM (1.5B)
# ---------------------------------------------------------------------------


_LLM_PROMPT = """Sei un classificatore di email italiane. Estrai dal testo:
1. type: uno di [appointment, task, bill_reminder, NON_RILEVANTE]
2. title: 5-10 parole sintetiche
3. due_at: ISO 8601 con timezone, oppure null se non specificata
4. location: stringa breve, oppure null
5. person: organizzazione o persona mittente, oppure null
6. notes: dettagli secondari (materiale da portare, ecc), oppure null
7. confidence: float 0-1

Rispondi SOLO con un oggetto JSON valido. Niente prosa.

Email:
SUBJECT: {subject}
BODY: {body}
"""


async def layer2_classify_local(*, subject: str, body: str) -> Proposal | None:
    """Run the local 1.5B with a strict-JSON prompt. Best-effort parse."""
    try:
        from cara.ai.llm import LLMUnavailableError, get_llm_service
    except Exception:  # noqa: BLE001
        return None

    truncated_body = body[:1200]
    prompt = _LLM_PROMPT.format(subject=subject[:180], body=truncated_body)

    try:
        llm = get_llm_service()
    except Exception:  # noqa: BLE001
        return None

    full = ""
    try:
        async for chunk in llm.generate(
            f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n",
            max_new_tokens=300,
        ):
            full += chunk.text
    except LLMUnavailableError:
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("email_understanding.layer2_failed", error=str(exc))
        return None

    return _parse_llm_json(full, source="local_llm")


# ---------------------------------------------------------------------------
# Layer 3 — cloud (opt-in)
# ---------------------------------------------------------------------------


async def layer3_classify_cloud(*, subject: str, body: str) -> Proposal | None:
    try:
        from cara.services import cloud_llm
    except Exception:  # noqa: BLE001
        return None

    if not cloud_llm.is_available():
        return None

    truncated_body = body[:1200]
    prompt = _LLM_PROMPT.format(subject=subject[:180], body=truncated_body)
    full = ""
    try:
        async for chunk in cloud_llm.cloud_chat_stream(prompt, max_tokens=400):
            full += chunk
    except cloud_llm.CloudLLMUnavailable as exc:
        log.warning("email_understanding.layer3_failed", error=str(exc))
        return None

    return _parse_llm_json(full, source="cloud_llm")


# ---------------------------------------------------------------------------
# Shared JSON parser
# ---------------------------------------------------------------------------


def _parse_llm_json(text: str, *, source: str) -> Proposal | None:
    """Robust JSON extraction from LLM output (handles trailing prose)."""
    if not text:
        return None
    # Find the first {...} block.
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        # Try a softer parse: strip newlines and re-attempt.
        try:
            data = json.loads(re.sub(r"\s+", " ", m.group(0)))
        except json.JSONDecodeError:
            return None

    ptype = str(data.get("type") or "NON_RILEVANTE").strip()
    if ptype not in ("appointment", "task", "bill_reminder", "NON_RILEVANTE"):
        ptype = "NON_RILEVANTE"

    due_str = data.get("due_at")
    due_at: datetime | None = None
    if due_str and isinstance(due_str, str):
        try:
            due_at = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            due_at = None

    confidence = float(data.get("confidence") or 0.0)
    confidence = max(0.0, min(1.0, confidence))

    return Proposal(
        proposal_type=ptype,
        title=str(data.get("title") or "")[:200],
        due_at=due_at,
        location=(data.get("location") or None),
        person=(data.get("person") or None),
        notes=(data.get("notes") or None),
        confidence=confidence,
        source_layer=source,
    )


# ---------------------------------------------------------------------------
# Public entry — run the pipeline
# ---------------------------------------------------------------------------


async def classify_email(
    *,
    subject: str,
    body: str,
    cloud_fallback: bool = False,
) -> Proposal:
    """Walk the pipeline. Always returns a Proposal (may be NON_RILEVANTE)."""
    layer1 = layer1_classify(subject=subject, body=body)
    if layer1.proposal_type == "NON_RILEVANTE":
        return layer1

    layer2 = await layer2_classify_local(subject=subject, body=body)
    candidate = layer2 if layer2 is not None else layer1

    if cloud_fallback and candidate.confidence < 0.7:
        layer3 = await layer3_classify_cloud(subject=subject, body=body)
        if layer3 is not None and layer3.confidence > candidate.confidence:
            candidate = layer3

    # Backfill from Layer 1 when Layer 2/3 missed structured fields.
    if candidate.due_at is None and layer1.due_at is not None:
        candidate.due_at = layer1.due_at
    if not candidate.location and layer1.location:
        candidate.location = layer1.location
    if not candidate.title:
        candidate.title = layer1.title

    return candidate


def proposal_to_args(p: Proposal) -> dict[str, Any]:
    """Serialise into the JSONB `proposal_args` shape."""
    return {
        "title": p.title,
        "due_date": p.due_at.isoformat() if p.due_at else None,
        "location": p.location,
        "person": p.person,
        "notes": p.notes,
    }
