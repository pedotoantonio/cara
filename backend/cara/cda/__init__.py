"""Content Discovery Agent.

Pipeline: intent → KB lookup → web search → discovery (per-type) → verification
→ playback → learning. See `/opt/cara/docs/cda-extension-spec.md` for the full
design.

Entry points:
- `discover()` — used by the chat tool router and the REST endpoint
- `record_feedback_*` — playback signals for the learning loop
"""

from cara.cda.base import (
    CdaError,
    CdaResult,
    ContentType,
    DiscoverRequest,
    Discovery,
    SearchHit,
)
from cara.cda.orchestrator import (
    discover,
    list_user_kb,
    record_feedback_regenerated,
    record_feedback_started,
    record_feedback_stopped,
    set_item_active,
)

__all__ = [
    "CdaError",
    "CdaResult",
    "ContentType",
    "DiscoverRequest",
    "Discovery",
    "SearchHit",
    "discover",
    "list_user_kb",
    "record_feedback_regenerated",
    "record_feedback_started",
    "record_feedback_stopped",
    "set_item_active",
]
