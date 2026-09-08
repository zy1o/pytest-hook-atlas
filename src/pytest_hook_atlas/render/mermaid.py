"""Render a HookGraph as a Mermaid flowchart.

Hook semantics are carried by node *shape* rather than colour: shapes survive
dark mode, printing, and colour-blindness, and need no CSS that a Mermaid
version bump might reinterpret.

    rectangle      an ordinary hook
    hexagon        firstresult - stops at the first non-None return
    parallelogram  historic - replays for plugins registered later
    subroutine     both of the above
"""

from __future__ import annotations

import re

from ..analysis import Hook, HookGraph
from ..doclinks import hook_url

SHAPES: dict[str, tuple[str, str]] = {
    "plain": ('["', '"]'),
    "firstresult": ('{{"', '"}}'),
    "historic": ('[/"', '"/]'),
    "both": ('[["', '"]]'),
}

MAX_TOOLTIP = 150
_RST_ROLE = re.compile(r":[a-z:]+:`(?P<target>[^`]+)`")
_RST_LITERAL = re.compile(r"``(?P<code>[^`]+)``")

LEGEND = (
    "| Shape | Meaning |\n"
    "| --- | --- |\n"
    "| rectangle | an ordinary hook |\n"
    "| hexagon | `firstresult` - the first non-`None` return wins, "
    "remaining implementations are skipped |\n"
    "| parallelogram | `historic` - replays for plugins registered later |\n"
    "| subroutine | both `firstresult` and `historic` |\n"
)


def _clean_summary(text: str) -> str:
    """Strip reStructuredText markup so docstrings read as plain prose.

    Hookspec docstrings are written for Sphinx, so they carry roles like
    ``:class:`~pytest.TestReport``` and inline literals.
    """
    text = _RST_ROLE.sub(lambda match: match.group("target").lstrip("~").split(".")[-1], text)
    text = _RST_LITERAL.sub(lambda match: match.group("code"), text)
    return " ".join(text.split())


def _tooltip(hook: Hook) -> str:
    """Mermaid tooltips are quoted strings; keep them single-line and quote-free."""
    summary = _clean_summary(hook.summary).replace('"', "'")
    if len(summary) > MAX_TOOLTIP:
        summary = summary[: MAX_TOOLTIP - 1].rsplit(" ", 1)[0] + "\u2026"
    if hook.call_count > 1:
        summary = f"{summary} (called {hook.call_count}x)"
    return summary


def node_ids(graph: HookGraph) -> dict[str, str]:
    """Stable, diff-friendly ids: sorted by hook name, not by discovery order."""
    return {name: f"h{index}" for index, name in enumerate(sorted(graph.hooks))}


def render(graph: HookGraph, base_url: str, direction: str = "LR") -> str:
    ids = node_ids(graph)
    lines = [f"flowchart {direction}"]

    for name in sorted(graph.hooks):
        hook = graph.hooks[name]
        open_shape, close_shape = SHAPES[hook.semantics]
        lines.append(f"    {ids[name]}{open_shape}{name}{close_shape}")

    for parent, child in graph.edges:
        if parent in ids and child in ids:
            arrow = "-.->" if parent == child else "-->"
            lines.append(f"    {ids[parent]} {arrow} {ids[child]}")

    for name in sorted(graph.hooks):
        tooltip = _tooltip(graph.hooks[name])
        url = hook_url(name, base_url)
        lines.append(f'    click {ids[name]} href "{url}" "{tooltip}" _blank')

    return "\n".join(lines)


def render_block(graph: HookGraph, base_url: str, direction: str = "LR") -> str:
    """A fenced Mermaid block, ready to drop into Markdown."""
    return f"```mermaid\n{render(graph, base_url, direction)}\n```"
