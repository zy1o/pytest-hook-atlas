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
from hook_atlas import flow

from pytest_hook_atlas import analysis
from pytest_hook_atlas import build as build_module

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACES = REPO_ROOT / "data" / "traces"

#: Nothing in the tooling requires a minimum number of hooks. A run that dies
#: in its first hookimpl should still be drawn exactly as it happened - that is
#: the point of pointing this at a real project. So each scenario declares what
#: *it* expects, in scenario.toml, and these tests check the scenarios we host
#: rather than imposing a rule on the tool.


@pytest.fixture(scope="session")
def site(tmp_path_factory):
    """Build the docs tree and its config entirely inside a temporary directory.

    Nothing is written into the repository, and nothing gitignored has to exist
    first - relying on a stale docs/ from a previous local build is how these
    tests passed here and failed in CI.
    """
    root = tmp_path_factory.mktemp("build")
    docs = root / "docs"
    config = root / "mkdocs.yml"
    build_module.build(REPO_ROOT, docs, TRACES, verify_links=False, config_path=config)
    return docs


@pytest.fixture(scope="session")
def builds():
    return build_module.collect(REPO_ROOT, TRACES)


def scenario_of(page: Path, builds) -> object:
    """The scenario a generated page belongs to, by directory name."""
    return next(item.scenario for item in builds if item.scenario.id == page.parent.name)


def group_pages(docs: Path) -> list[Path]:
    return sorted(
        path
        for path in (docs / "scenarios").rglob("*.md")
        # every group page carries this heading; a version that merely points at
        # its group is a redirect stub, and a distributed scenario heads its
        # sections per process rather than "The whole run"
        if path.stem not in {"index", "latest"} and "## How this was produced" in path.read_text()
    )


#: A page documents one process per section: "The whole run" when a scenario
#: runs in a single process, "The controller" and "Worker gw0" when it does
#: not. Phase headings repeat per process and carry the process in brackets, so
#: that their anchors stay unique - these helpers let the sweep below ask the
#: same questions of both page shapes.
OVERVIEW_HEADING = re.compile(r"^## (The whole run|The controller|Worker \S+)$", re.M)


def process_sections(text: str) -> dict[str, str]:
    """Each process section on a page, keyed by its heading."""
    found = {}
    for match in OVERVIEW_HEADING.finditer(text):
        end = OVERVIEW_HEADING.search(text, match.end())
        found[match.group(1)] = text[match.end() : end.start() if end else len(text)]
    return found


def overview_of(section: str) -> str:
    """The part of a process section before its first phase."""
    return re.split(r"^#{2,3} ", section, maxsplit=1, flags=re.M)[0]


def phase_sections(text: str, phase) -> list[str]:
    """Every rendering of one phase on a page, one per process."""
    heading = re.compile(rf"^#{{2,3}} {re.escape(phase.title)}(?: \(\S+\))?$", re.M)
    following = re.compile(r"^#{2,3} ", re.M)
    found = []
    for match in heading.finditer(text):
        end = following.search(text, match.end())
        found.append(text[match.end() : end.start() if end else len(text)])
    return found


# --------------------------------------------------------------------------
# the captures themselves


def collapsed(trace, floor: int) -> bool:
    """Did this capture see fewer hooks than its scenario expects?"""
    return floor > 0 and trace["stats"]["unique_hooks"] < floor


def test_every_capture_meets_the_expectation_its_scenario_declares(builds):
    """A collapsed run is the failure mode that looks like success.

    The floor comes from the scenario, not from here: `internal-error` sees 22
    hooks by design, and a scenario that declares no floor is not checked at
    all.
    """
    for item in builds:
        floor = item.scenario.min_hooks
        for version, process, trace in item.captures():
            observed = trace["stats"]["unique_hooks"]
            assert not collapsed(trace, floor), (
                f"{item.scenario.id}/{process} on pytest {version} saw only {observed} hooks, "
                f"below its declared minimum of {floor}"
            )


def test_every_scenario_reaches_the_hooks_it_exists_for(builds):
    """Each scenario names the hooks it was built to capture.

    A count alone is a crude proxy - this says what the scenario is *for*, and
    fails if it quietly stops doing it.
    """
    for item in builds:
        if not item.scenario.expects:
            continue
        # what a scenario exists to show is a property of the whole run, so a
        # distributed scenario satisfies it across its processes: the xdist
        # controller never runs a test, and its workers never serialize one
        for version in item.traces:
            observed = {
                hook
                for process in item.processes(version)
                for hook in analysis.full_graph(item.trace(version, process)).hooks
            }
            # A hook the release does not declare cannot be reached, and
            # expecting it means nothing: pytest_markeval_namespace arrived in
            # 6.2.0, so the edge-cases scenario cannot exercise it on 6.1. The
            # trace says which hooks its release had, so nothing needs
            # declaring twice.
            declared = {
                hook
                for process in item.processes(version)
                for hook in item.trace(version, process).get("hookspecs", {})
            }
            missing = [
                hook for hook in item.scenario.expects if hook in declared and hook not in observed
            ]
            assert not missing, f"{item.scenario.id} on pytest {version} never reached {missing}"


def test_the_collapse_check_respects_a_declared_floor():
    """Guard the guard.

    every-hook-conftest shipped broken on pytest 8.0 and 9.0: its conftest
    failed to import, the run collapsed to four hooks, and the page carried on
    claiming every hook was implemented.
    """
    assert collapsed({"stats": {"unique_hooks": 4}}, floor=30)
    assert not collapsed({"stats": {"unique_hooks": 38}}, floor=30)
    # a scenario that ends early on purpose declares no floor, so nothing fires
    assert not collapsed({"stats": {"unique_hooks": 4}}, floor=0)


def test_no_capture_recorded_a_desync(builds):
    for item in builds:
        for version, process, trace in item.captures():
            assert trace["desyncs"] == [], f"{item.scenario.id}/{process} on {version}"


def test_every_capture_exercises_every_phase(builds):
    """All four stages must appear - unless the session ends early by design."""
    for item in builds:
        if not item.scenario.complete_run:
            continue
        for version, process, trace in item.captures():
            present = {
                phase.key
                for phase in analysis.PHASES
                if flow.phase_variants(analysis.phase_subtrees(trace, phase))
            }
            missing = {phase.key for phase in analysis.PHASES} - present
            assert not missing, (
                f"{item.scenario.id}/{process} on pytest {version} is missing {missing}"
            )


# --------------------------------------------------------------------------
# every group page


def test_group_pages_were_generated(site, builds):
    expected = sum(len(item.rendered) for item in builds)

    assert len(group_pages(site)) == expected


def test_every_group_page_has_every_stage(site, builds):
    """All four phases on every page - unless the run ended early by design."""
    for page in group_pages(site):
        scenario = scenario_of(page, builds)
        text = page.read_text()
        sections = process_sections(text)
        assert sections, f"{page} has no overview"
        if not scenario.complete_run:
            continue
        for phase in analysis.PHASES:
            assert phase_sections(text, phase), f"{page} is missing '{phase.title}'"


def test_every_stage_is_followed_by_a_rendered_diagram(site):
    """A heading with no diagram under it is the shape of a silent failure."""
    for page in group_pages(site):
        text = page.read_text()
        for phase in analysis.PHASES:
            for section in phase_sections(text, phase):
                assert '<div class="ha-diagram">' in section, (
                    f"{page.name}: {phase.key} has no diagram"
                )
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


def test_the_overview_columns_are_all_present_and_clickable(site, builds):
    """Every phase the run actually reached gets a clickable column."""
    for page in group_pages(site):
        text = page.read_text()
        for label, section in process_sections(text).items():
            overview = overview_of(section)
            for phase in analysis.PHASES:
                if not re.search(
                    rf"^#{{2,3}} {re.escape(phase.title)}(?: \(\S+\))?$", section, re.M
                ):
                    continue
                assert f"ha&#45;{phase.key}" in overview, (
                    f"{page.name} ({label}): no {phase.key} column"
                )
                heading = re.search(
                    rf"^#{{2,3}} ({re.escape(phase.title)}(?: \(\S+\))?)$", section, re.M
                ).group(1)
                anchor = build_module.heading_anchor(heading)
                assert f'xlink:href="#{anchor}"' in overview, (
                    f"{page.name} ({label}): {phase.key} not clickable"
                )


def test_every_group_page_carries_provenance_and_a_picker(site):
    for page in group_pages(site):
        text = page.read_text()
        assert "## How this was produced" in text, page.name
        assert "github.com/zy1o/pytest-hook-atlas/tree/main/scenarios/" in text, page.name
        assert 'class="ha-version-picker"' in text, page.name
        assert "<option " in text, page.name


def test_every_group_page_lists_its_hooks(site, builds):
    for page in group_pages(site):
        scenario = scenario_of(page, builds)
        text = page.read_text()
        assert "## Every hook observed" in text, page.name
        assert "Implemented by, in call order" in text, page.name
        rows = [line for line in text.splitlines() if line.startswith("| [`pytest_")]
        assert len(rows) >= max(scenario.min_hooks, 1), f"{page.name} lists only {len(rows)} hooks"


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
    config = (site.parent / "mkdocs.yml").read_text()
    nav = config.split("nav:", 1)[1].split("not_in_nav:", 1)[0]

    for target in re.findall(r"([\w./-]+\.md)", nav):
        assert (site / target).exists(), f"nav points at missing page {target}"


# --------------------------------------------------------------------------
# the rendered HTML, where several of these bugs only became visible


@pytest.fixture(scope="session")
def html(site, tmp_path_factory):
    """Render the real site from the temporary build. Needs the docs extra."""
    pytest.importorskip("mkdocs", reason="site rendering needs the docs extra")
    import subprocess

    out = tmp_path_factory.mktemp("site")
    config = site.parent / "mkdocs.yml"
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


def test_call_order_is_consistent_with_pluggys_ordering_rules(builds):
    """Wrappers outermost, then tryfirst, then plain, then trylast.

    A strong check on the whole capture path: if implementations were recorded
    in pluggy's storage order rather than its call order - as they were once -
    every call here would violate this.
    """

    def rank(impl):
        if impl.get("wrapper") or impl.get("hookwrapper"):
            return 0
        if impl.get("tryfirst"):
            return 1
        if impl.get("trylast"):
            return 3
        return 2

    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(node.get("children", []))

    for item in builds:
        for version, process, trace in item.captures():
            for node in walk(trace["calls"]):
                # the trace stores pluggy's list verbatim, which is reversed
                order = [rank(impl) for impl in reversed(node["impls"])]
                assert order == sorted(order), (
                    f"{item.scenario.id}/{process} on {version}: {node['name']} implementations "
                    "are not in pluggy's call order"
                )


def test_ordering_flags_are_shown_beside_implementations(site):
    for page in group_pages(site):
        text = page.read_text()
        if "ha-flags" not in text:
            continue
        assert "[wrapper]" in text or "[tryfirst]" in text or "[trylast]" in text
        return
    raise AssertionError("no page annotated any ordering flags")
