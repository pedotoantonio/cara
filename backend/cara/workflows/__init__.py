"""Workflow engine — multimodal "input → action plan → confirmation".

A workflow is the pattern behind "scarica un'immagine, capisce cos'è,
propone azioni": receipt → spesa updated + budget logged, bill →
reminder + budget, recipe → ingredients added, prescription → dose
reminders.

Every concrete workflow shares the same shape:

    classify → extract → propose → execute

`classify` decides whether this workflow is the right one for the input
(usually a quick keyword or signature check). `extract` pulls structured
data. `propose` translates that data into a list of `ProposedAction`s
the user reviews. `execute` runs the actions once confirmed.

This module ships only the infrastructure (Protocol, registry, types).
Concrete workflows (ReceiptWorkflow, BillWorkflow, RecipeWorkflow,
PrescriptionWorkflow, FridgeWorkflow) come in Epic 3.
"""

from cara.workflows.base import (
    ClassifyResult,
    ExecutionResult,
    ProposedAction,
    StructuredData,
    Workflow,
    WorkflowError,
    WorkflowInput,
    WorkflowRegistry,
    get_default_registry,
)

__all__ = [
    "ClassifyResult",
    "ExecutionResult",
    "ProposedAction",
    "StructuredData",
    "Workflow",
    "WorkflowError",
    "WorkflowInput",
    "WorkflowRegistry",
    "get_default_registry",
]
