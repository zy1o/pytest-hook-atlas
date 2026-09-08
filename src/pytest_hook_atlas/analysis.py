"""Turn a raw trace into the deduplicated graph a diagram is drawn from.

A trace records every hook call, so ``pytest_runtest_protocol`` and its whole
subtree appear once per test. A diagram wants the *shape*: each distinct
containment relationship once, in the order it was first observed.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Hook:
    """A hook as it appears in a diagram."""

    name: str
    historic: bool = False
    firstresult: bool = False
    summary: str = ""
    call_count: int = 0
    plugins: tuple[str, ...] = ()

    @property
    def semantics(self) -> str:
        """Class name used for styling; see the site legend."""
        if self.historic and self.firstresult:
            return "both"
        if self.historic:
            return "historic"
        if self.firstresult:
            return "firstresult"
        return "plain"


@dataclass
class HookGraph:
    """Deduplicated containment graph: which hooks are called inside which."""

    key: str
    title: str
    description: str = ""
    hooks: dict[str, Hook] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.hooks)


@dataclass(frozen=True)
class Phase:
    """A slice of the run, rendered as its own diagram."""

    key: str
    title: str
    anchors: tuple[str, ...]
    description: str


#: Derived from the observed tree shape, not from prose in the pytest docs.
PHASES: tuple[Phase, ...] = (
    Phase(
        key="startup",
        title="Startup and configuration",
        anchors=("pytest_load_initial_conftests", "pytest_configure", "pytest_sessionstart"),
        description=(
            "Everything before collection begins: initial conftests are loaded, "
            "plugins register, and the session is configured."
        ),
    ),
    Phase(
        key="collection",
        title="Collection",
        anchors=("pytest_collection",),
        description=(
            "Finding tests. Note that pytest_make_collect_report recurses - "
            "directories contain directories contain files."
        ),
    ),
    Phase(
        key="runtest",
        title="The run-test loop",
        anchors=("pytest_runtestloop",),
        description=(
            "The per-test protocol: setup, call, teardown, each reported "
            "separately. This subtree repeats once per collected test."
        ),
    ),
    Phase(
        key="finish",
        title="Session finish",
        anchors=("pytest_sessionfinish", "pytest_unconfigure"),
        description="Summary reporting and teardown of the session.",
    ),
)


def load_trace(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def walk(nodes: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Depth-first walk over raw trace nodes."""
    for node in nodes:
        yield node
        yield from walk(node.get("children", []))


def find_subtrees(nodes: list[dict[str, Any]], names: tuple[str, ...]) -> list[dict[str, Any]]:
    """All nodes matching ``names``, without descending into a match twice."""
    found: list[dict[str, Any]] = []

    def visit(current: list[dict[str, Any]]) -> None:
        for node in current:
            if node["name"] in names:
                found.append(node)
            else:
                visit(node.get("children", []))

    visit(nodes)
    return found


def build_graph(
    trace: dict[str, Any],
    nodes: list[dict[str, Any]],
    key: str = "full",
    title: str = "Full hook flow",
    description: str = "",
) -> HookGraph:
    """Collapse raw trace nodes into a deduplicated containment graph."""
    hookspecs = trace.get("hookspecs", {})
    counts: Counter[str] = Counter()
    plugins: dict[str, list[str]] = {}
    edges: list[tuple[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()

    for node in walk(nodes):
        counts[node["name"]] += 1
        known = plugins.setdefault(node["name"], [])
        for impl in node.get("impls", []):
            name = impl.get("plugin")
            if name and name not in known:
                known.append(name)
        for child in node.get("children", []):
            edge = (node["name"], child["name"])
            if edge not in seen_edges:
                seen_edges.add(edge)
                edges.append(edge)

    hooks = {
        name: Hook(
            name=name,
            historic=bool(hookspecs.get(name, {}).get("historic")),
            firstresult=bool(hookspecs.get(name, {}).get("firstresult")),
            summary=hookspecs.get(name, {}).get("summary", ""),
            call_count=count,
            plugins=tuple(plugins.get(name, ())),
        )
        for name, count in counts.items()
    }
    roots = [node["name"] for node in nodes]
    return HookGraph(
        key=key,
        title=title,
        description=description,
        hooks=hooks,
        edges=edges,
        roots=list(dict.fromkeys(roots)),
    )


def phase_graphs(trace: dict[str, Any]) -> list[HookGraph]:
    """One graph per phase, skipping phases this scenario never exercised."""
    graphs = []
    for phase in PHASES:
        subtrees = find_subtrees(trace["calls"], phase.anchors)
        if not subtrees:
            continue
        graphs.append(build_graph(trace, subtrees, phase.key, phase.title, phase.description))
    return graphs


def full_graph(trace: dict[str, Any]) -> HookGraph:
    return build_graph(
        trace,
        trace["calls"],
        key="full",
        title="Full hook flow",
        description="Every hook observed in this scenario, deduplicated.",
    )


CONFTEST_MARKER = "conftest.py"


def conftest_blind_spots(graph: HookGraph) -> list[str]:
    """Hooks that fired without any ``conftest.py`` implementation participating.

    In a scenario whose conftest implements *every* declared hook, this is a
    direct measurement of the hooks a ``conftest.py`` cannot serve: the call
    happened, the implementation was registered, and it was still not invoked -
    because the conftest had not been imported when the hook fired, or sits
    below the level the hook applies to.
    """
    return sorted(
        name
        for name, hook in graph.hooks.items()
        if not any(CONFTEST_MARKER in str(plugin) for plugin in hook.plugins)
    )
