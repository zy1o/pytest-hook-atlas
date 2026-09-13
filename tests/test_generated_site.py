"""A sweep across everything the site generates.

The bugs this project has actually shipped were not logic errors - they were
pages that built cleanly and said the wrong thing. A stylesheet whose selectors
matched nothing. A plugin name swallowed as an HTML tag. A scenario whose
conftest failed to import, so its page advertised "every hook implemented"
while showing four.

So these tests ask of every generated page: are all the stages here, and did
they render? Not "did the build succeed".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from pytest_hook_atlas import analysis, flow
from pytest_hook_atlas import build as build_module

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACES = REPO_ROOT / "data" / "traces"

#: A scenario that traced correctly sees most of pytest's hooks. A conftest
#: that failed to import collapses the run to a handful, which is how the
#: every-hook-conftest scenario was quietly broken on two pytest versions.
MINIMUM_HOOKS = 30


@pytest.fixture(scope="session")
def site(tmp_path_factory):
    docs = tmp_path_factory.mktemp("docs")
    build_module.build(REPO_ROOT, docs, TRACES, verify_links=False)
    return docs


@pytest.fixture(scope="session")
def builds():
    return build_module.collect(REPO_ROOT, TRACES)


def group_pages(docs: Path) -> list[Path]:
    return sorted(
        path
        for path in (docs / "scenarios").rglob("*.md")
        if path.stem not in {"index", "latest"} and "## The whole run" in path.read_text()
    )


# --------------------------------------------------------------------------
# the captures themselves


def collapsed(trace) -> bool:
    """Did this capture see so few hooks that the run must have failed?"""
    return trace["stats"]["unique_hooks"] < MINIMUM_HOOKS


def test_every_capture_saw_a_plausible_number_of_hooks(builds):
    """A collapsed run is the failure mode that looks like success."""
    for item in builds:
        for version, trace in item.traces.items():
            observed = trace["stats"]["unique_hooks"]
            assert not collapsed(trace), (
                f"{item.scenario.id} on pytest {version} saw only {observed} hooks - "
                "the run probably collapsed"
            )


def test_the_collapse_check_recognises_a_collapsed_run():
    """Guard the guard.

    The every-hook-conftest scenario shipped broken on pytest 8.0 and 9.0: its
    generated conftest implemented a deprecated hook, and a deprecated argument,
    both of which pytest turns into import errors. The run collapsed to five
    calls and four hooks, and the page went on claiming every hook was
    implemented.
    """
    assert collapsed({"stats": {"unique_hooks": 4}})
    assert not collapsed({"stats": {"unique_hooks": 38}})


def test_no_capture_recorded_a_desync(builds):
    for item in builds:
        for version, trace in item.traces.items():
            assert trace["desyncs"] == [], f"{item.scenario.id} on {version}"


def test_every_capture_exercises_every_phase(builds):
    """All four stages must appear, or the diagrams below them are missing."""
    for item in builds:
        for version, trace in item.traces.items():
            present = {
                phase.key
                for phase in analysis.PHASES
                if flow.phase_variants(analysis.find_subtrees(trace["calls"], phase.anchors))
            }
            missing = {phase.key for phase in analysis.PHASES} - present
            assert not missing, f"{item.scenario.id} on pytest {version} is missing {missing}"


# --------------------------------------------------------------------------
# every group page


def test_group_pages_were_generated(site, builds):
    expected = sum(len(item.rendered) for item in builds)

    assert len(group_pages(site)) == expected


def test_every_group_page_has_every_stage(site):
    """The headline assertion: all four phases, on every page."""
    required = ["## The whole run", *[f"## {phase.title}" for phase in analysis.PHASES]]

    for page in group_pages(site):
        text = page.read_text()
        for heading in required:
            assert heading in text, f"{page.name} is missing '{heading}'"


def test_every_stage_is_followed_by_a_rendered_diagram(site):
    """A heading with no diagram under it is the shape of a silent failure."""
    for page in group_pages(site):
        text = page.read_text()
        for phase in analysis.PHASES:
            section = text.split(f"## {phase.title}", 1)[1].split("\n## ", 1)[0]
            assert '<div class="ha-diagram">' in section, f"{page.name}: {phase.key} has no diagram"
            assert "<svg" in section, f"{page.name}: {phase.key} diagram is empty"


def test_every_diagram_is_well_formed_and_not_collapsed(site):
    """Guards the graph-margin trap, which put an 864pt offset in every viewBox,
    and any future change that renders a diagram with no content."""
    for page in group_pages(site):
        for svg in re.findall(r"<svg .*?</svg>", page.read_text(), re.S):
            size = re.search(r'width="(\d+)pt" height="(\d+)pt"', svg)
            assert size, f"{page.name}: diagram has no dimensions"
            width, height = int(size.group(1)), int(size.group(2))
            assert 40 < width < 6000 and 40 < height < 12000, f"{page.name}: {width}x{height}pt"

            viewbox = re.search(r'viewBox="([\d.]+) ([\d.]+)', svg)
            assert viewbox, f"{page.name}: diagram has no viewBox"
            assert float(viewbox.group(1)) < 50, f"{page.name}: viewBox is offset"


def test_every_diagram_links_its_hooks_to_documentation(site):
    for page in group_pages(site):
        text = page.read_text()
        assert "pytest.hookspec." in text, f"{page.name} has no documentation links"
        assert "docs.pytest.org" in text


def test_the_overview_columns_are_all_present_and_clickable(site):
    for page in group_pages(site):
        overview = page.read_text().split("## The whole run", 1)[1].split("\n## ", 1)[0]
        for phase in analysis.PHASES:
            assert f"ha&#45;{phase.key}" in overview, f"{page.name}: no {phase.key} column"
            anchor = build_module.heading_anchor(phase.title)
            assert f'xlink:href="#{anchor}"' in overview, f"{page.name}: {phase.key} not clickable"


def test_every_group_page_carries_provenance_and_a_picker(site):
    for page in group_pages(site):
        text = page.read_text()
        assert "## How this was produced" in text, page.name
        assert "github.com/zy1o/pytest-hook-atlas/tree/main/scenarios/" in text, page.name
        assert 'class="ha-version-picker"' in text, page.name
        assert "<option " in text, page.name


def test_every_group_page_lists_its_hooks(site):
    for page in group_pages(site):
        text = page.read_text()
        assert "## Every hook observed" in text, page.name
        assert "Implemented by, in call order" in text, page.name
        rows = [line for line in text.splitlines() if line.startswith("| [`pytest_")]
        assert len(rows) >= MINIMUM_HOOKS, f"{page.name} lists only {len(rows)} hooks"


# --------------------------------------------------------------------------
# rendering hygiene


def test_no_footnote_reference_is_left_dangling(site):
    for page in site.rglob("*.md"):
        text = page.read_text()
        referenced = set(re.findall(r"\[\^([\w.]+)\](?!:)", text))
        defined = set(re.findall(r"^\[\^([\w.]+)\]:", text, re.M))
        assert referenced <= defined, f"{page.name}: undefined footnotes {referenced - defined}"


SVG_BLOCK = re.compile(r"<svg .*?</svg>", re.S)

#: Tags the generator writes deliberately. Anything else in angle brackets is
#: prose that markdown will treat as HTML and silently drop.
INTENTIONAL_TAGS = {"br", "div", "span", "meta", "option", "select", "label"}


def test_angle_bracket_names_are_inside_code_spans(site):
    """A plugin named <anonymous> is swallowed as an HTML tag when written bare.

    Diagrams are stripped first: Graphviz emits its own <title> elements, and
    those are not prose.
    """
    for page in site.rglob("*.md"):
        prose = SVG_BLOCK.sub("", page.read_text())
        for line in prose.splitlines():
            for match in re.finditer(r"<([a-z]+)>", line):
                if match.group(1) in INTENTIONAL_TAGS:
                    continue
                assert line[: match.start()].count("`") % 2 == 1, (
                    f"{page.name}: <{match.group(1)}> is not inside a code span"
                )


def test_no_page_is_an_empty_stub(site):
    for page in site.rglob("*.md"):
        text = page.read_text().strip()
        assert text.startswith(("#", "<meta")), f"{page.name} has no heading"
        assert len(text) > 120, f"{page.name} is suspiciously short"


def test_top_level_pages_all_exist(site):
    for name in ("index.md", "versions.md", "changes.md", "design-notes.md", "changelog.md"):
        assert (site / name).exists(), f"{name} was not generated"


def test_the_navigation_points_only_at_pages_that_exist(site):
    nav = (REPO_ROOT / "mkdocs.yml").read_text().split("nav:", 1)[1].split("not_in_nav:", 1)[0]

    for target in re.findall(r"([\w./-]+\.md)", nav):
        assert (site / target).exists(), f"nav points at missing page {target}"


# --------------------------------------------------------------------------
# the rendered HTML, where several of these bugs only became visible


@pytest.fixture(scope="session")
def html(site, tmp_path_factory):
    """Build the real site. Skipped where mkdocs is not installed."""
    pytest.importorskip("mkdocs", reason="site rendering needs the docs extra")
    import subprocess

    out = tmp_path_factory.mktemp("site")
    config = REPO_ROOT / "mkdocs.yml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mkdocs",
            "build",
            "--strict",
            "-f",
            str(config),
            "--site-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return out


def test_html_renders_a_diagram_on_every_group_page(html):
    pages = [
        p for p in (html / "scenarios").rglob("index.html") if "The whole run" in p.read_text()
    ]
    assert pages, "no group pages were rendered"

    for page in pages:
        text = page.read_text()
        assert text.count("<svg") >= len(analysis.PHASES), f"{page} lost a diagram"
        assert "ha-diagram" in text


def test_html_keeps_documentation_links_clickable(html):
    for page in (html / "scenarios").rglob("index.html"):
        text = page.read_text()
        if "The whole run" not in text:
            continue
        assert 'xlink:href="https://docs.pytest.org' in text, f"{page}: links are not anchors"


def test_html_renders_footnotes_rather_than_leaving_markup(html):
    for page in (html / "scenarios").rglob("index.html"):
        text = page.read_text()
        assert "[^pytest_" not in text, f"{page}: raw footnote markup leaked"


def test_html_did_not_swallow_the_anonymous_plugin(html):
    """Written bare it is parsed as a tag and vanishes."""
    pages = [p for p in (html / "scenarios").rglob("index.html") if "anonymous" in p.read_text()]

    assert pages, "expected the anonymous plugin somewhere in the rendered site"
    for page in pages:
        assert "&lt;anonymous&gt;" in page.read_text(), f"{page}: escaped form is missing"
