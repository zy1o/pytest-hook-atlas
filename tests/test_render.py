"""Tests for the Graphviz flow renderer."""

from __future__ import annotations

import re

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


def test_a_subtitle_separator_survives_escaping():
    """The separator is an HTML entity, and label text is escaped.

    Escaping the joined subtitle turned `&#183;` into a literal `&amp;#183;` on
    every node carrying one - which is most of them.
    """
    svg = dot.render_inline_svg([FlowNode("pytest_configure")], HOOKSPECS, BASE, "startup", {})

    assert "&amp;#183;" not in svg


def test_a_folded_summary_names_its_hooks_and_links_to_nothing():
    """A summary is not a hook: no documentation to open, and it must not read
    as a step that ran once."""
    summary = FlowNode("40 further steps of 2 hooks", folded=("pytest_a", "pytest_b"))

    svg = dot.render_inline_svg([summary], HOOKSPECS, BASE, "runtest", {})

    assert "pytest_a" in svg and "pytest_b" in svg
    assert "ha&#45;summary" in svg
    assert "stroke-dasharray" in svg
    assert "xlink:href" not in svg


def test_overview_columns_start_at_the_same_height():
    """A cluster's label is two lines when its hook has semantics to show and
    one when it does not, which pushed some column tops 12pt below others."""
    columns = [
        ("startup", "Startup", [FlowNode("pytest_configure", children=[FlowNode("a")])]),
        ("runtest", "Run", [FlowNode("pytest_runtest_protocol", children=[FlowNode("b")])]),
    ]

    svg = dot.to_inline_svg(dot.build_columns(columns, HOOKSPECS, BASE, {}))

    tops = []
    for key, _, _ in columns:
        index = svg.index(f'class="cluster ha&#45;column ha&#45;{key}"')
        path = re.search(r'<path[^>]*\sd="([^"]+)"', svg[index : index + 1200]).group(1)
        tops.append(min(float(y) for _, y in re.findall(r"([-\d.]+),([-\d.]+)", path)))

    assert len(set(tops)) == 1, f"column tops differ: {tops}"


def test_the_alignment_anchor_leaves_nothing_visible():
    """It is an invisible node and an invisible edge; Graphviz drops both."""
    columns = [("startup", "Startup", [FlowNode("pytest_configure")])]

    svg = dot.to_inline_svg(dot.build_columns(columns, HOOKSPECS, BASE, {}))

    assert "_top" not in svg
    assert svg.count("<polygon") == 0, "an invisible edge must draw no arrowhead"
