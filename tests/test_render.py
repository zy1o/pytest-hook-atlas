"""Tests for the Mermaid and Graphviz renderers."""

from __future__ import annotations

import pytest

from pytest_hook_atlas.analysis import Hook, HookGraph
from pytest_hook_atlas.render import dot, mermaid

BASE = "https://docs.pytest.org/en/stable/reference/reference.html"


@pytest.fixture
def graph():
    hooks = {
        "pytest_configure": Hook("pytest_configure", historic=True, summary="Cfg.", call_count=1),
        "pytest_runtestloop": Hook("pytest_runtestloop", firstresult=True, call_count=1),
        "pytest_runtest_setup": Hook("pytest_runtest_setup", call_count=8),
        "pytest_addoption": Hook("pytest_addoption", historic=True, firstresult=True),
    }
    return HookGraph(
        key="t",
        title="T",
        hooks=hooks,
        edges=[
            ("pytest_runtestloop", "pytest_runtest_setup"),
            ("pytest_runtestloop", "pytest_runtestloop"),
        ],
        roots=["pytest_configure", "pytest_runtestloop"],
    )


def test_shape_encodes_hook_semantics(graph):
    output = mermaid.render(graph, BASE)

    assert '[/"pytest_configure"/]' in output  # historic
    assert '{{"pytest_runtestloop"}}' in output  # firstresult
    assert '["pytest_runtest_setup"]' in output  # plain
    assert '[["pytest_addoption"]]' in output  # both


def test_self_recursion_uses_a_dotted_edge(graph):
    lines = mermaid.render(graph, BASE).splitlines()
    ids = mermaid.node_ids(graph)
    loop = ids["pytest_runtestloop"]

    assert f"    {loop} -.-> {loop}" in lines


def test_every_node_links_to_its_documentation(graph):
    output = mermaid.render(graph, BASE)

    for name in graph.hooks:
        assert f"#pytest.hookspec.{name}" in output
    assert output.count("click ") == len(graph.hooks)


def test_node_ids_are_stable_across_runs(graph):
    assert mermaid.node_ids(graph) == mermaid.node_ids(graph)


def test_tooltips_are_stripped_of_rst_and_quotes():
    hook = Hook(
        name="x",
        summary="Process the :class:`~pytest.TestReport` for ``item``.",
        call_count=3,
    )
    tooltip = mermaid._tooltip(hook)

    assert ":class:" not in tooltip
    assert "``" not in tooltip
    assert '"' not in tooltip
    assert "TestReport" in tooltip
    assert "(called 3x)" in tooltip


def test_long_tooltips_truncate_on_a_word_boundary():
    hook = Hook(name="x", summary="word " * 100)
    tooltip = mermaid._tooltip(hook)

    assert len(tooltip) <= mermaid.MAX_TOOLTIP + 20
    assert tooltip.endswith("…")


def test_graphviz_shapes_mirror_the_mermaid_vocabulary():
    assert set(dot.SHAPES) == set(mermaid.SHAPES)


def test_svg_renders_with_clickable_nodes(graph, tmp_path):
    written = dot.render_svg(graph, BASE, tmp_path / "g.svg")

    assert written.exists()
    assert "pytest.hookspec.pytest_configure" in written.read_text()
