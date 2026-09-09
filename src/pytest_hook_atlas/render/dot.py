"""Render captured flows with Graphviz.

Graphviz rather than Mermaid because this shape needs three things Mermaid does
badly: deterministic layout, real nesting via clusters, and one type size across
every diagram instead of scaling each to fit its container. Mermaid rendered a
two-node diagram enormous and a fourteen-node one unreadably small.

**Two views, deliberately.** The overview lays the phases out as columns, left
to right, with steps running top to bottom inside each - the whole session at a
glance. It is depth-limited, because at full depth collection alone is 29
nested steps and the page runs to roughly two and a half screens. Detail lives
in per-phase diagrams below. That the collection column dwarfs the others is
not imbalance to correct: it is where pytest's complexity actually is, and the
picture should say so.

**Colour is CSS, not baked in.** Nodes carry class attributes naming their
phase and shading step; the stylesheet supplies the actual colours. That keeps
the diagrams following the site's light/dark toggle without re-rendering, and
means the palette can change without recapturing anything.
"""

from __future__ import annotations

import html
import math
import re
from pathlib import Path
from typing import Any

import graphviz

from ..doclinks import hook_url
from ..flow import FlowNode

FONT = "Helvetica,Arial,sans-serif"
SEPARATOR = " &#183; "

#: Discrete shading levels. Frequency maps onto these rather than onto a
#: continuous colour so the palette can live in CSS.
SHADE_STEPS = 6

#: Phase hues, chosen by simulating dichromatic vision and maximising the worst
#: case separation across normal, protanopia, deuteranopia and tritanopia. The
#: obvious "Google" palette scored dE 3.9 between two of its four hues under
#: deuteranopia - effectively identical. This set scores 48.5.
#:
#: Deliberately no green and no alarm-red: phases are categories, not statuses,
#: and a traffic-light reading would imply an ordering ("collection passed,
#: runtest is a warning") that does not exist.
#:
#: Colour is redundant throughout - every column also carries a title, a border
#: and a fixed position - so it accelerates reading rather than carrying it.
PHASE_HUES = {
    "startup": "#332288",
    "collection": "#56B4E9",
    "runtest": "#DDCC77",
    "finish": "#882255",
}


def semantics_of(name: str, hookspecs: dict[str, Any]) -> list[str]:
    """Human-readable tags, shown as a subtitle instead of encoded in a shape.

    Shapes required a legend lookup to decode; words do not.
    """
    spec = hookspecs.get(name, {})
    return [
        tag
        for tag, on in (
            ("historic", spec.get("historic")),
            ("firstresult", spec.get("firstresult")),
        )
        if on
    ]


def shade_step(count: int, peak: int) -> int:
    """Bucket a call count onto ``SHADE_STEPS`` levels, logarithmically.

    Counts span 1 to ~80 in a single run, dominated by a few hot hooks. On a
    linear ramp everything below about 10 would collapse into the palest step
    and the scale would say nothing.
    """
    if peak <= 1 or count <= 1:
        return 0
    ratio = math.log1p(count) / math.log1p(peak)
    return min(SHADE_STEPS - 1, int(ratio * SHADE_STEPS))


def _label(node: FlowNode, hookspecs: dict[str, Any], total: int | None) -> str:
    """Hook name, then a muted subtitle carrying semantics and frequency."""
    subtitle = semantics_of(node.name, hookspecs)
    if node.count > 1:
        subtitle.append(f"x{node.count}")
    elif total and total > 1:
        subtitle.append(f"{total}x in run")

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
    def __init__(
        self,
        hookspecs: dict[str, Any],
        base_url: str,
        phase: str = "startup",
        totals: dict[str, int] | None = None,
        prefix: str = "",
    ) -> None:
        self.hookspecs = hookspecs
        self.base_url = base_url
        self.phase = phase
        # ids must be unique across the whole graph: one builder per column
        # meant restarting counters, so clusters collided and Graphviz silently
        # dropped every column after the first
        self.prefix = prefix
        self.totals = totals or {}
        self.peak = max(self.totals.values(), default=1)
        self._counter = 0

    def _uid(self) -> str:
        self._counter += 1
        return f"{self.prefix}n{self._counter}"

    def _classes(self, node: FlowNode, kind: str) -> str:
        total = self.totals.get(node.name, node.count)
        return f"ha-{kind} ha-{self.phase} ha-shade-{shade_step(total, self.peak)}"

    def emit(self, graph: Any, nodes: list[FlowNode]) -> list[tuple[str, str, str | None]]:
        elements: list[tuple[str, str, str | None]] = []
        for node in nodes:
            total = self.totals.get(node.name)
            common = {
                "label": _label(node, self.hookspecs, total),
                "href": hook_url(node.name, self.base_url),
                "target": "_blank",
                "tooltip": node.name,
            }
            if node.is_leaf:
                node_id = self._uid()
                graph.node(
                    node_id,
                    shape="box",
                    style="rounded,filled",
                    **common,
                    **{"class": self._classes(node, "node")},
                )
                elements.append((node_id, node_id, None))
            else:
                cluster_name = f"cluster_{self._uid()}"
                with graph.subgraph(name=cluster_name) as sub:
                    sub.attr(
                        labeljust="l",
                        style="rounded,filled",
                        # cluster margin is in points, unlike the root graph's
                        margin="10",
                        **common,
                        **{"class": self._classes(node, "cluster")},
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


def _new_graph() -> graphviz.Digraph:
    dot = graphviz.Digraph()
    dot.attr(
        compound="true",
        rankdir="TB",
        bgcolor="transparent",
        nodesep="0.20",
        ranksep="0.28",
        fontname=FONT,
        fontsize="11",
        # graph margin is in INCHES; cluster margin above is in points. Setting
        # this to 12 once meant twelve inches and put an 864pt offset in every
        # viewBox.
        margin="0.08",
    )
    dot.attr("node", fontname=FONT, fontsize="11", margin="0.13,0.06", penwidth="1.3")
    dot.attr("edge", arrowsize="0.65")
    dot.attr("graph", fontname=FONT, fontsize="11")
    return dot


def build(
    nodes: list[FlowNode],
    hookspecs: dict[str, Any],
    base_url: str,
    phase: str = "startup",
    totals: dict[str, int] | None = None,
) -> graphviz.Digraph:
    """One phase, rendered as a vertical flow."""
    dot = _new_graph()
    builder = _Builder(hookspecs, base_url, phase, totals)
    builder.chain(dot, builder.emit(dot, nodes))
    return dot


def build_columns(
    phases: list[tuple[str, str, list[FlowNode]]],
    hookspecs: dict[str, Any],
    base_url: str,
    totals: dict[str, int] | None = None,
) -> graphviz.Digraph:
    """The overview: one column per phase, laid out left to right.

    Phases are rendered as clusters with no edges between them, which is what
    makes Graphviz place them side by side rather than stacking them.
    """
    dot = _new_graph()
    for key, title, nodes in phases:
        if not nodes:
            continue
        with dot.subgraph(name=f"cluster_phase_{key}") as column:
            column.attr(
                label=title.upper(),
                labeljust="l",
                style="rounded",
                fontsize="12",
                margin="14",
                penwidth="1.6",
                **{"class": f"ha-column ha-{key}"},
            )
            builder = _Builder(hookspecs, base_url, key, totals, prefix=f"{key}_")
            builder.chain(column, builder.emit(column, nodes))
    return dot


_XML_DECLARATION = re.compile(r"<\?xml.*?\?>\s*|<!DOCTYPE.*?>\s*", re.DOTALL)
_SVG_COMMENT = re.compile(r"<!--.*?-->\s*", re.DOTALL)


def to_inline_svg(dot: graphviz.Digraph) -> str:
    """SVG markup ready to embed directly in a page.

    Inlined rather than referenced with ``<img>`` for two reasons: links inside
    an ``<img>``-rendered SVG are not clickable, and external CSS cannot reach
    inside one to theme it.

    Width and height are kept: diagrams are sized to be read at 100% and capped
    by CSS, rather than each being scaled to its container.
    """
    source = dot.pipe(format="svg").decode("utf-8")
    source = _XML_DECLARATION.sub("", source)
    return _SVG_COMMENT.sub("", source).strip()


def render_inline_svg(
    nodes: list[FlowNode],
    hookspecs: dict[str, Any],
    base_url: str,
    phase: str = "startup",
    totals: dict[str, int] | None = None,
) -> str:
    return to_inline_svg(build(nodes, hookspecs, base_url, phase, totals))


def render_svg_file(
    nodes: list[FlowNode], hookspecs: dict[str, Any], base_url: str, out_path: str | Path
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_inline_svg(nodes, hookspecs, base_url))
    return out_path
