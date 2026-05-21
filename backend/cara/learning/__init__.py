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
from cara.learning.habits import (
    detect_and_persist as habits_detect_and_persist,
    detect_in_events as habits_detect_in_events,
    list_pending as habits_list_pending,
    review_candidate as habits_review_candidate,
)
from cara.learning.reflective import (
    detect_router_miss_clusters as reflective_miss_clusters,
    detect_tool_failure_clusters as reflective_failure_clusters,
    run_weekly as reflective_run_weekly,
)
from cara.learning.semantic import (
    confirm_fact as semantic_confirm_fact,
    deactivate_fact as semantic_deactivate_fact,
    detect_facts as semantic_detect_facts,
    extract_facts_async as semantic_extract_facts_async,
    list_facts as semantic_list_facts,
    save_fact as semantic_save_fact,
    save_facts_from_message as semantic_save_facts_from_message,
    top_k_for_query as semantic_top_k_for_query,
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
    "habits_detect_and_persist",
    "habits_detect_in_events",
    "habits_list_pending",
    "habits_review_candidate",
    "reflective_failure_clusters",
    "reflective_miss_clusters",
    "reflective_run_weekly",
    "semantic_confirm_fact",
    "semantic_deactivate_fact",
    "semantic_detect_facts",
    "semantic_extract_facts_async",
    "semantic_list_facts",
    "semantic_save_fact",
    "semantic_save_facts_from_message",
    "semantic_top_k_for_query",
    "tool_metrics_recent_failures",
    "tool_metrics_record",
    "tool_metrics_stats",
    "tool_metrics_top_failures",
]
