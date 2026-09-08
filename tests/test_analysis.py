"""Tests for collapsing a raw trace into a diagram graph."""

from __future__ import annotations

import pytest

from pytest_hook_atlas import analysis


def node(name, children=(), impls=()):
    return {"name": name, "seq": 0, "depth": 0, "impls": list(impls), "children": list(children)}


@pytest.fixture
def trace():
    """Two runs of the same protocol, so dedup has something to collapse."""
    protocol = lambda: node(  # noqa: E731
        "pytest_runtest_protocol",
        [
            node("pytest_runtest_setup", [node("pytest_fixture_setup")]),
            node("pytest_runtest_call", impls=[{"plugin": "runner"}]),
        ],
    )
    return {
        "schema_version": 1,
        "environment": {"pytest": "9.1.1"},
        "hookspecs": {
            "pytest_runtestloop": {"firstresult": True, "historic": False, "summary": "loop"},
            "pytest_runtest_protocol": {"firstresult": True, "historic": False, "summary": ""},
            "pytest_configure": {"firstresult": False, "historic": True, "summary": "cfg"},
            "pytest_runtest_setup": {"firstresult": False, "historic": False, "summary": ""},
            "pytest_runtest_call": {"firstresult": False, "historic": False, "summary": ""},
            "pytest_fixture_setup": {"firstresult": True, "historic": False, "summary": ""},
        },
        "calls": [
            node("pytest_configure"),
            node("pytest_runtestloop", [protocol(), protocol()]),
        ],
    }


def test_repeated_subtrees_collapse_to_one_edge(trace):
    graph = analysis.full_graph(trace)

    assert graph.edges.count(("pytest_runtestloop", "pytest_runtest_protocol")) == 1
    assert graph.hooks["pytest_runtest_protocol"].call_count == 2


def test_semantics_classification(trace):
    graph = analysis.full_graph(trace)

    assert graph.hooks["pytest_configure"].semantics == "historic"
    assert graph.hooks["pytest_runtestloop"].semantics == "firstresult"
    assert graph.hooks["pytest_runtest_setup"].semantics == "plain"


def test_semantics_handles_both_flags():
    hook = analysis.Hook(name="x", historic=True, firstresult=True)
    assert hook.semantics == "both"


def test_plugin_provenance_is_collected(trace):
    graph = analysis.full_graph(trace)
    assert graph.hooks["pytest_runtest_call"].plugins == ("runner",)


def test_phase_graphs_skip_phases_this_scenario_never_ran(trace):
    keys = {graph.key for graph in analysis.phase_graphs(trace)}

    assert "runtest" in keys
    assert "startup" in keys
    assert "collection" not in keys  # nothing was collected in this fixture


def test_find_subtrees_does_not_descend_into_a_match(trace):
    found = analysis.find_subtrees(trace["calls"], ("pytest_runtest_protocol",))
    assert len(found) == 2


def test_conftest_blind_spots_lists_hooks_no_conftest_served():
    """Hooks that fired with no conftest implementation participating."""
    graph = analysis.HookGraph(
        key="t",
        title="T",
        hooks={
            "pytest_configure": analysis.Hook(
                "pytest_configure", plugins=("/tmp/p/conftest.py", "runner")
            ),
            "pytest_load_initial_conftests": analysis.Hook(
                "pytest_load_initial_conftests", plugins=("main",)
            ),
        },
    )

    assert analysis.conftest_blind_spots(graph) == ["pytest_load_initial_conftests"]
