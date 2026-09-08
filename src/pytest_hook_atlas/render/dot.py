"""Render a HookGraph with Graphviz.

Mermaid handles the per-phase diagrams well, but its layout degrades on the
full graph (40+ nodes, 40+ edges). Graphviz stays legible there, so the "full
map" page uses this instead.
"""

from __future__ import annotations

from pathlib import Path

import graphviz

from ..analysis import HookGraph
from ..doclinks import hook_url

#: Mirrors the Mermaid shape vocabulary so the legend reads the same either way.
SHAPES = {
    "plain": "box",
    "firstresult": "hexagon",
    "historic": "parallelogram",
    "both": "doubleoctagon",
}


def build(graph: HookGraph, base_url: str, rankdir: str = "LR") -> graphviz.Digraph:
    dot = graphviz.Digraph(name=graph.key, strict=True)
    dot.attr(rankdir=rankdir, bgcolor="transparent")
    dot.attr("node", style="filled", fillcolor="white", fontname="Helvetica", fontsize="10")
    dot.attr("edge", color="#666666", arrowsize="0.7")

    for name in sorted(graph.hooks):
        hook = graph.hooks[name]
        dot.node(
            name,
            label=name,
            shape=SHAPES[hook.semantics],
            href=hook_url(name, base_url),
            target="_blank",
            tooltip=hook.summary[:150] or name,
        )

    for parent, child in graph.edges:
        dot.edge(parent, child, style="dashed" if parent == child else "solid")

    return dot


def render_svg(graph: HookGraph, base_url: str, out_path: str | Path, rankdir: str = "LR") -> Path:
    """Write an SVG. Returns the path written.

    ``graphviz.render`` appends its own extension, so the stem is passed in and
    the final path reconstructed.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stem = out_path.with_suffix("")
    build(graph, base_url, rankdir).render(str(stem), format="svg", cleanup=True)
    return stem.with_suffix(".svg")
