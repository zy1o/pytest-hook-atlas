"""Contrast guarantees for the generated diagram stylesheet.

These are regression tests for a real defect: the original palette put two of
its four hues at 3.9:1 under deuteranopia, and raw hues used as column titles
scored 1.3:1 and 1.6:1 against the backgrounds they sat on - effectively
invisible. Anyone changing PHASE_HUES should be told by a failing test rather
than by a reader who cannot read the diagram.
"""

from __future__ import annotations

import pytest

from pytest_hook_atlas.render import css
from pytest_hook_atlas.render.dot import PHASE_HUES, SHADE_STEPS

WCAG_AA = 4.5
WCAG_LARGE = 3.0

THEMES = {
    "light": (css.LIGHT_BACKGROUND, css.MAX_TINT_LIGHT, (33, 33, 33), (90, 90, 90)),
    "dark": (css.DARK_BACKGROUND, css.MAX_TINT_DARK, (227, 227, 227), (180, 180, 180)),
}


def test_contrast_ratio_matches_known_values():
    assert css.contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0, abs=0.01)
    assert css.contrast((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("phase", sorted(PHASE_HUES))
def test_column_titles_are_readable_in_both_themes(phase, theme):
    """Raw #DDCC77 scores 1.6:1 on white and raw #332288 scores 1.3:1 on slate."""
    background = THEMES[theme][0]
    title = css.readable_on(PHASE_HUES[phase], background)

    assert css.contrast(css._rgb(title), background) >= WCAG_AA


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("phase", sorted(PHASE_HUES))
def test_body_and_muted_text_stay_readable_on_every_fill(phase, theme):
    """The tint ceiling exists to keep this true on the darkest shading step."""
    background, ceiling, body, muted = THEMES[theme]

    for fill in css._fills(PHASE_HUES[phase], background, ceiling):
        rgb = css._rgb(fill)
        assert css.contrast(body, rgb) >= WCAG_AA, f"{phase}/{theme} body on {fill}"
        assert css.contrast(muted, rgb) >= WCAG_LARGE, f"{phase}/{theme} muted on {fill}"


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("phase", sorted(PHASE_HUES))
def test_node_borders_are_visible_against_their_own_fill(phase, theme):
    background, ceiling, _, _ = THEMES[theme]
    stroke = css._rgb(css.readable_on(PHASE_HUES[phase], background, WCAG_LARGE))

    assert css.contrast(stroke, background) >= WCAG_LARGE


def test_fills_run_from_background_toward_the_hue():
    fills = css._fills(PHASE_HUES["collection"], css.LIGHT_BACKGROUND, css.MAX_TINT_LIGHT)

    assert len(fills) == SHADE_STEPS
    assert fills[0] == "#FFFFFF"
    assert fills[0] != fills[-1]


def test_stylesheet_covers_every_phase_and_step_in_both_themes():
    sheet = css.stylesheet()

    for phase in PHASE_HUES:
        for step in range(SHADE_STEPS):
            assert f".ha-{phase}.ha-shade-{step}" in sheet
    assert '[data-md-color-scheme="slate"]' in sheet


def test_readable_on_returns_the_hue_unchanged_when_it_already_passes():
    """#332288 is already 12:1 on white and should not be darkened further."""
    assert css.readable_on("#332288", css.LIGHT_BACKGROUND) == "#332288"


def _rendered_svg():
    from pytest_hook_atlas.flow import FlowNode
    from pytest_hook_atlas.render import dot

    nodes = [FlowNode("pytest_configure", children=[FlowNode("pytest_plugin_registered")])]
    return dot.render_inline_svg(nodes, {}, "https://example/ref.html", "startup", {})


def test_shapes_are_wrapped_so_child_selectors_would_miss_them():
    """Regression: Graphviz wraps any shape carrying an href in <g><a>.

    The stylesheet used `> path`, which matched nothing, so every node kept
    Graphviz's default grey fill while the text switched to the theme colour -
    light text on light grey, unreadable in dark mode.
    """
    import xml.etree.ElementTree as ET

    root = ET.fromstring(_rendered_svg())
    ns = {"svg": "http://www.w3.org/2000/svg"}
    classed = [
        element
        for element in root.iter("{http://www.w3.org/2000/svg}g")
        if "ha-node" in (element.get("class") or "")
    ]
    assert classed, "expected at least one classed node group"

    group = classed[0]
    assert group.find("svg:path", ns) is None, "shape is no longer wrapped; revisit selectors"
    assert group.find(".//svg:path", ns) is not None, "shape must be reachable as a descendant"


def test_stylesheet_uses_descendant_selectors_for_shapes():
    sheet = css.stylesheet()

    for line in sheet.splitlines():
        if ".ha-shade-" in line or ".ha-column" in line:
            assert "> path" not in line, f"child selector cannot reach wrapped shapes: {line}"
            assert "> polygon" not in line, f"child selector cannot reach wrapped shapes: {line}"


def test_graphviz_groups_are_siblings_not_nested():
    """Why a descendant selector is safe: it cannot leak into another node."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(_rendered_svg())
    graph = next(
        element
        for element in root.iter("{http://www.w3.org/2000/svg}g")
        if (element.get("class") or "") == "graph"
    )
    classed = [child for child in graph if "ha-" in (child.get("class") or "")]
    for group in classed:
        nested = [d for d in group.iter() if "ha-node" in (d.get("class") or "")]
        assert len(nested) <= 1, "groups must not nest, or descendant selectors would leak"


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_stylesheet_fills_match_the_baked_renderer(theme):
    """The CSS path and the baked-theme path must agree.

    Diagrams on the site are coloured by CSS, but previews and exports bake the
    colours in. Only the baked path can be rendered to an image locally - no
    available renderer applies CSS inside an SVG - so this equality is what
    makes a preview trustworthy evidence about the real site.
    """
    import re

    sheet = css.stylesheet()
    prefix = '[data-md-color-scheme="slate"] ' if theme == "dark" else ""
    background, ceiling = css.theme_settings(theme)

    for phase, hue in PHASE_HUES.items():
        baked = css._fills(hue, background, ceiling)
        for step, expected in enumerate(baked):
            selector = f"{prefix}.ha-diagram .ha-{phase}.ha-shade-{step}"
            match = re.search(
                re.escape(f"{selector} path,")
                + r"\n"
                + re.escape(f"{selector} polygon")
                + r" \{ fill: (#[0-9A-F]{6});",
                sheet,
            )
            assert match, f"no rule for {theme}/{phase}/{step}"
            assert match.group(1) == expected
