"""Thin async wrapper around Gmail v1 REST.

═══════════════════════════════════════════════════════════════════════
  READ-ONLY GUARANTEE — questo modulo NON modifica MAI le email.

  In particolare: il flag UNREAD su Gmail NON viene mai rimosso da
  Cara. Se l'utente apre Gmail dopo che Cara ha estratto una proposta,
  l'email resta marcata come non letta esattamente come prima.

  Difese in profondità:

   1. OAuth scope: `gmail.readonly` + `gmail.metadata`. Nessuno dei due
      autorizza `messages.modify` — Google ritornerebbe 403 anche se
      provassimo.

   2. API surface esposta da questo file: SOLO `list_messages()` e
      `get_message()`. Nessuna funzione che chiami `messages.modify`,
      `messages.batchModify`, `messages.trash`, `messages.untrash`,
      `messages.delete`, `messages.send`.

   3. Test di regressione: `tests/unit/test_gmail_readonly_guarantee.py`
      grep-asserta che nessuna stringa "modify"/"trash"/"send" appaia
      mai nel modulo.

  Se in futuro qualcuno vuole aggiungere "marca come letta dopo aver
  creato il task" — questo richiede:
     a) cambio scope OAuth → `gmail.modify`, RE-CONSENT di tutti gli utenti
     b) toggle admin esplicito (default OFF)
     c) review privacy
  Non aggiungerlo silenziosamente.
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import base64
import re
from typing import Any

import httpx
import structlog


log = structlog.get_logger(__name__)


_API_BASE = "https://gmail.googleapis.com/gmail/v1"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def list_messages(
    token: str, *, query: str, max_results: int = 50,
) -> list[str]:
    """Return a list of message ids matching the Gmail search `query`."""
    out: list[str] = []
    page_token: str | None = None
    async with httpx.AsyncClient(timeout=20.0) as c:
        while len(out) < max_results:
            params: dict[str, Any] = {"q": query, "maxResults": min(50, max_results - len(out))}
            if page_token:
                params["pageToken"] = page_token
            resp = await c.get(
                f"{_API_BASE}/users/me/messages",
                headers=_headers(token), params=params,
            )
            if resp.status_code == 401:
                raise PermissionError("token expired")
            resp.raise_for_status()
            body = resp.json()
            for m in body.get("messages", []):
                out.append(m["id"])
                if len(out) >= max_results:
                    break
            page_token = body.get("nextPageToken")
            if not page_token:
                break
    return out


async def get_message(
    token: str, *, message_id: str, format: str = "full",
) -> dict[str, Any]:
    """Fetch a single message. format: 'metadata' | 'full' | 'raw'."""
    async with httpx.AsyncClient(timeout=20.0) as c:
        resp = await c.get(
            f"{_API_BASE}/users/me/messages/{message_id}",
            headers=_headers(token),
            params={"format": format},
        )
        resp.raise_for_status()
    return resp.json()


def _decode_b64url(s: str | None) -> str:
    if not s:
        return ""
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def extract_text(payload: dict[str, Any] | None) -> str:
    """Walk the MIME parts and return the best plaintext we can find.

    Prefer text/plain over text/html; strip HTML tags as a last resort.
    """
    if not payload:
        return ""
    mime = payload.get("mimeType", "")
    body = payload.get("body") or {}
    if mime == "text/plain":
        return _decode_b64url(body.get("data"))
    if "parts" in payload:
        # Prefer plain over html.
        for p in payload["parts"]:
            if p.get("mimeType") == "text/plain":
                t = extract_text(p)
                if t.strip():
                    return t
        for p in payload["parts"]:
            if p.get("mimeType") == "text/html":
                t = extract_text(p)
                if t.strip():
                    return _strip_html(t)
        # Fallback: first non-empty subpart.
        for p in payload["parts"]:
            t = extract_text(p)
            if t.strip():
                return t
    if mime == "text/html":
        return _strip_html(_decode_b64url(body.get("data")))
    if body.get("data"):
        return _decode_b64url(body.get("data"))
    return ""


def _strip_html(html: str) -> str:
    """Quick-and-dirty HTML→text. Good enough for email previews."""
    t = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<script.*?</script>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    # Decode common HTML entities.
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&")
         .replace("&lt;", "<").replace("&gt;", ">")
         .replace("&quot;", '"').replace("&#39;", "'"))
    return re.sub(r"\s+", " ", t).strip()


def parse_headers(message: dict[str, Any]) -> dict[str, str]:
    """Return {from, to, subject, date} from the message envelope."""
    out: dict[str, str] = {}
    headers = (message.get("payload") or {}).get("headers", [])
    wanted = {"from", "to", "subject", "date"}
    for h in headers:
        name = (h.get("name") or "").lower()
        if name in wanted:
            out[name] = h.get("value", "")
    return out


def from_address(message: dict[str, Any]) -> str:
    """Extract just the email part of the From header."""
    raw = parse_headers(message).get("from", "")
    m = re.search(r"<([^>]+)>", raw)
    if m:
        return m.group(1).strip().lower()
    return raw.strip().lower()
