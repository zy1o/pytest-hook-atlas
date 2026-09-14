"""pytest's own shape: what its phases are, and what a conftest cannot serve.

The machinery for slicing a trace into phases lives in :mod:`hook_atlas`. What
lives here is the description of *pytest* - which hooks open which phase, and
what to call them.
"""

from __future__ import annotations

from hook_atlas.analysis import (
    WHOLE_RUN,
    Hook,
    HookGraph,
    Phase,
    build_graph,
    find_subtrees,
    full_graph,
    load_trace,
    phase_subtrees,
    resolve_phases,
    walk,
)

__all__ = [
    "PHASES",
    "WHOLE_RUN",
    "Hook",
    "HookGraph",
    "Phase",
    "build_graph",
    "conftest_blind_spots",
    "find_subtrees",
    "full_graph",
    "load_trace",
    "phase_graphs",
    "phase_subtrees",
    "resolve_phases",
    "walk",
]


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
        title="The run-test protocol",
        anchors=("pytest_runtest_protocol",),
        description=(
            "`pytest_runtestloop` runs this once per collected test. Note the "
            "rhythm: setup, call and teardown are each followed by their own "
            "`makereport` and `logreport` pair - three reports per test, not one."
        ),
        fallback_anchors=("pytest_runtestloop",),
    ),
    Phase(
        key="finish",
        title="Session finish",
        anchors=("pytest_sessionfinish", "pytest_unconfigure"),
        description="Summary reporting and teardown of the session.",
    ),
)


def phase_graphs(trace: dict) -> list[HookGraph]:
    """One graph per pytest phase, skipping phases this scenario never ran."""
    from hook_atlas.analysis import phase_graphs as _phase_graphs

    return _phase_graphs(trace, PHASES)


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
