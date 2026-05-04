"""SSE frame helper for the chat streaming endpoint.

Pulled out of `chat.py` to make the hot-path orchestrator shorter and
to give us a single place to evolve the wire format (e.g. when we add
TTS audio chunks alongside text tokens).
"""

from __future__ import annotations

import json
from typing import Any


def sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    """Encode one SSE frame: `event: <name>\\ndata: <json>\\n\\n` as UTF-8 bytes.

    `ensure_ascii=False` so Italian accents / emoji travel as UTF-8 in
    the data line — the consumer is `EventSource`/`fetch` in the
    browser, which expects UTF-8 by spec.
    """
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
