"""Wallet widget engine — composable cards for the family dashboard.

The Wallet is the "first thing the family sees when they open CARA":
a personalised dashboard with task summary, presence, weather, quick
actions, etc. Each card in the dashboard is a Widget — an async function
that returns a typed `WidgetData` payload the frontend renders.

This module ships the infrastructure (Protocol, registry, types,
WidgetContext). The catalog of concrete widgets lives in
`cara.widgets.catalog`.
"""

from cara.widgets.base import (
    Widget,
    WidgetContext,
    WidgetData,
    WidgetError,
    WidgetRegistry,
    WidgetSize,
    get_default_registry,
)

__all__ = [
    "Widget",
    "WidgetContext",
    "WidgetData",
    "WidgetError",
    "WidgetRegistry",
    "WidgetSize",
    "get_default_registry",
]
