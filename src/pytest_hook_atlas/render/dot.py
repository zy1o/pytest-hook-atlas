"""Render an ordered flow with Graphviz.

Graphviz rather than Mermaid because this shape needs three things Mermaid does
not do well: deterministic layout, real nesting via clusters, and typography
that stays the same size across diagrams instead of scaling each one to fit.

Colours are deliberately left to CSS. Nodes and edges carry ``class``
attributes and the SVG is inlined into the page, so the site's light/dark
toggle restyles the diagrams without re-rendering them.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

import graphviz

from ..doclinks import hook_url
from ..flow import FlowNode

FONT = "Helvetica,Arial,sans-serif"
SEPARATOR = " &#183; "


def semantics_of(name: str, hookspecs: dict[str, Any]) -> list[str]:
    """Human-readable tags, shown as a subtitle instead of encoded in a shape."""
    spec = hookspecs.get(name, {})
    return [
        tag
        for tag, on in (
            ("historic", spec.get("historic")),
            ("firstresult", spec.get("firstresult")),
        )
        if on
    ]


def _label(node: FlowNode, hookspecs: dict[str, Any]) -> str:
    """An HTML-like label: hook name, then a muted subtitle line."""
    subtitle = semantics_of(node.name, hookspecs)
    if node.count > 1:
        subtitle = [*subtitle, f"x{node.count}"]

    rows = [f"<TR><TD>{html.escape(node.name)}</TD></TR>"]
    if subtitle:
        rows.append(
            '<TR><TD><FONT POINT-SIZE="9" COLOR="#8a8a8a">'
            f"{SEPARATOR.join(subtitle)}</FONT></TD></TR>"
        )
    return (
        '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="1">'
        + "".join(rows)
        + "</TABLE>>"
    )


class _Builder:
    def __init__(self, hookspecs: dict[str, Any], base_url: str) -> None:
        self.hookspecs = hookspecs
        self.base_url = base_url
        self._counter = 0

    def _uid(self) -> str:
        self._counter += 1
        return f"n{self._counter}"

    def emit(self, graph: Any, nodes: list[FlowNode]) -> list[tuple[str, str, str | None]]:
        """Render a sequence of steps. Returns (entry, exit, cluster) per step."""
        elements: list[tuple[str, str, str | None]] = []
        for node in nodes:
            if node.is_leaf:
                node_id = self._uid()
                graph.node(
                    node_id,
                    label=_label(node, self.hookspecs),
                    shape="box",
                    style="rounded",
                    href=hook_url(node.name, self.base_url),
                    target="_blank",
                    tooltip=node.name,
                    **{"class": "ha-node"},
                )
                elements.append((node_id, node_id, None))
            else:
                cluster_name = f"cluster_{self._uid()}"
                with graph.subgraph(name=cluster_name) as sub:
                    sub.attr(
                        label=_label(node, self.hookspecs),
                        labeljust="l",
                        style="rounded",
                        href=hook_url(node.name, self.base_url),
                        target="_blank",
                        tooltip=node.name,
                        # cluster margin is in points, unlike the root graph's
                        margin="10",
                        **{"class": "ha-cluster"},
                    )
                    inner = self.emit(sub, node.children)
                    self.chain(sub, inner)
                elements.append((inner[0][0], inner[-1][1], cluster_name))
        return elements

    def chain(self, graph: Any, elements: list[tuple[str, str, str | None]]) -> None:
        """Connect consecutive steps - this is the ordering the trace recorded."""
        for (_, exit_a, cluster_a), (entry_b, _, cluster_b) in zip(
            elements, elements[1:], strict=False
        ):
            attrs: dict[str, str] = {"class": "ha-edge"}
            if cluster_a:
                attrs["ltail"] = cluster_a
            if cluster_b:
                attrs["lhead"] = cluster_b
            graph.edge(exit_a, entry_b, **attrs)


def build(nodes: list[FlowNode], hookspecs: dict[str, Any], base_url: str) -> graphviz.Digraph:
    dot = graphviz.Digraph()
    dot.attr(
        compound="true",
        rankdir="TB",
        bgcolor="transparent",
        nodesep="0.22",
        ranksep="0.30",
        fontname=FONT,
        fontsize="11",
        # graph margin is in INCHES; cluster margin below is in points
        margin="0.08",
    )
    dot.attr("node", fontname=FONT, fontsize="11", color="#5f6368", margin="0.14,0.07")
    dot.attr("edge", color="#9aa0a6", arrowsize="0.7")
    dot.attr("graph", fontname=FONT, fontsize="11", color="#9aa0a6")

    builder = _Builder(hookspecs, base_url)
    elements = builder.emit(dot, nodes)
    builder.chain(dot, elements)
    return dot


_XML_DECLARATION = re.compile(r"<\?xml.*?\?>\s*|<!DOCTYPE.*?>\s*", re.DOTALL)
_SVG_COMMENT = re.compile(r"<!--.*?-->\s*", re.DOTALL)


def render_inline_svg(nodes: list[FlowNode], hookspecs: dict[str, Any], base_url: str) -> str:
    """SVG markup ready to embed directly in a page.

    Inlined rather than referenced with ``<img>`` for two reasons: links inside
    an ``<img>``-rendered SVG are not clickable, and external CSS cannot reach
    inside one to theme it.
    """
    source = build(nodes, hookspecs, base_url).pipe(format="svg").decode("utf-8")
    source = _XML_DECLARATION.sub("", source)
    source = _SVG_COMMENT.sub("", source)
    # width/height are kept: the diagrams are sized to be read at 100%, and
    # CSS caps them with max-width rather than scaling every one differently
    return source.strip()


def render_svg_file(
    nodes: list[FlowNode], hookspecs: dict[str, Any], base_url: str, out_path: str | Path
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_inline_svg(nodes, hookspecs, base_url))
    return out_path
