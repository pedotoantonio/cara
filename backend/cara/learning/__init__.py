"""Learning layer — episodic, semantic, procedural, reflective memory.

The learning layer turns raw events into knowledge that compounds:

- `episodic`  — append-only event log (Step 0.3). Every chat turn, tool
                call, router decision lives here. Substrate for everything
                else.
- `semantic`  — facts about users (allergies, preferences, schedules).
                Extracted explicitly from the user's chat ("ricorda che…")
                or via deterministic patterns. Stored as embeddings for
                top-k retrieval. (Step 2.x)
- `procedural`— skills CARA knows how to execute. Lives in the existing
                `cara.skills` package; this module just wraps usage stats.
                (Step 2.x)
- `reflective`— weekly batch that clusters router-misses and proposes
                new patterns/skills for admin review. (Step 8.x)

Order of build matches how each layer depends on the prior one.
"""

from cara.learning.episodic import (
    cleanup_old as episodic_cleanup_old,
    query as episodic_query,
    record as episodic_record,
)
from cara.learning.tool_metrics import (
    record_attempt as tool_metrics_record,
    recent_failures as tool_metrics_recent_failures,
    stats as tool_metrics_stats,
    top_failure_classes as tool_metrics_top_failures,
)

__all__ = [
    "episodic_cleanup_old",
    "episodic_query",
    "episodic_record",
    "tool_metrics_recent_failures",
    "tool_metrics_record",
    "tool_metrics_stats",
    "tool_metrics_top_failures",
]
