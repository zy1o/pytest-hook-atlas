"""Tests for the Graphviz flow renderer."""

from __future__ import annotations

import pytest

from pytest_hook_atlas.flow import FlowNode
from pytest_hook_atlas.render import dot

BASE = "https://docs.pytest.org/en/stable/reference/reference.html"

HOOKSPECS = {
    "pytest_runtest_protocol": {"firstresult": True, "historic": False},
    "pytest_configure": {"firstresult": False, "historic": True},
    "pytest_runtest_setup": {"firstresult": False, "historic": False},
}


@pytest.fixture
def nodes():
    return [
        FlowNode("pytest_configure"),
        FlowNode(
            "pytest_runtest_protocol",
            count=5,
            children=[FlowNode("pytest_runtest_setup", count=2)],
        ),
    ]


def test_semantics_are_words_not_shapes():
    assert dot.semantics_of("pytest_configure", HOOKSPECS) == ["historic"]
    assert dot.semantics_of("pytest_runtest_protocol", HOOKSPECS) == ["firstresult"]
    assert dot.semantics_of("pytest_runtest_setup", HOOKSPECS) == []
    assert dot.semantics_of("unknown_hook", HOOKSPECS) == []


def test_repeat_counts_appear_in_labels(nodes):
    svg = dot.render_inline_svg(nodes, HOOKSPECS, BASE)

    assert "x5" in svg
    assert "x2" in svg


def test_every_hook_links_to_its_documentation(nodes):
    svg = dot.render_inline_svg(nodes, HOOKSPECS, BASE)

    for name in ("pytest_configure", "pytest_runtest_protocol", "pytest_runtest_setup"):
        assert f"#pytest.hookspec.{name}" in svg


def test_inline_svg_is_embeddable(nodes):
    """No XML declaration or doctype, or it cannot be inlined into a page."""
    svg = dot.render_inline_svg(nodes, HOOKSPECS, BASE)

    assert svg.startswith("<svg")
    assert "<?xml" not in svg
    assert "DOCTYPE" not in svg


def test_svg_keeps_its_natural_size(nodes):
    """Sizing is capped by CSS, not by scaling each diagram to its container."""
    svg = dot.render_inline_svg(nodes, HOOKSPECS, BASE)

    assert 'width="' in svg[:200]
    assert 'height="' in svg[:200]


def test_diagram_is_not_absurdly_offset(nodes):
    """Guards the graph-margin-is-inches trap that produced an 864pt offset."""
    svg = dot.render_inline_svg(nodes, HOOKSPECS, BASE)
    viewbox = svg.split('viewBox="')[1].split('"')[0].split()

    assert float(viewbox[0]) < 50
    assert float(viewbox[1]) < 50


def test_nesting_becomes_a_cluster(nodes):
    svg = dot.render_inline_svg(nodes, HOOKSPECS, BASE)

    assert "cluster" in svg


def test_styling_hooks_are_present_for_css_theming(nodes):
    """Colours come from CSS so the site's dark mode restyles the diagram."""
    svg = dot.render_inline_svg(nodes, HOOKSPECS, BASE)

    assert 'class="node' in svg
    assert 'class="edge' in svg
    assert 'fill="transparent"' in svg or "transparent" in svg
