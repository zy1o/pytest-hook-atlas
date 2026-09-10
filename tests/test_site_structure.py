"""Tests for the generated page structure.

The URL guarantees are the point: readers and search engines both suffer when
a published link stops resolving.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_hook_atlas import build as build_module

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACES = REPO_ROOT / "data" / "traces"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    docs = tmp_path_factory.mktemp("docs")
    pages = build_module.build(REPO_ROOT, docs, TRACES, verify_links=False)
    return docs, pages


@pytest.fixture(scope="module")
def builds():
    return build_module.collect(REPO_ROOT, TRACES)


def test_every_captured_version_has_a_page(built, builds):
    """Canonical or alias - a version must never 404.

    Backfilling older releases can extend a group backwards and move its first
    version, so the canonical URL can change. Aliases mean nothing breaks.
    """
    docs, _ = built
    for item in builds:
        directory = docs / "scenarios" / item.scenario.id
        rendered = {v for group in item.rendered for v in group.versions}
        for version in rendered:
            assert (directory / f"{version}.md").exists(), f"{item.scenario.id} {version}"


def test_alias_pages_point_at_their_group(built, builds):
    docs, _ = built
    for item in builds:
        directory = docs / "scenarios" / item.scenario.id
        for group in item.rendered:
            for version in group.versions:
                if version == group.key:
                    continue
                text = (directory / f"{version}.md").read_text()
                assert f"url=../{group.key}/" in text
                assert f"{group.key}.md" in text


def test_group_pages_are_named_by_their_first_version(built, builds):
    docs, _ = built
    for item in builds:
        for group in item.rendered:
            page = docs / "scenarios" / item.scenario.id / f"{group.key}.md"
            assert page.exists()
            assert group.key == group.versions[0]


def test_latest_points_at_the_newest_group(built, builds):
    docs, _ = built
    for item in builds:
        latest = docs / "scenarios" / item.scenario.id / "latest.md"
        assert latest.exists()
        assert f"url=../{item.latest.key}/" in latest.read_text()


def test_version_picker_covers_every_rendered_version(built, builds):
    docs, _ = built
    item = builds[0]
    page = (docs / "scenarios" / item.scenario.id / f"{item.latest.key}.md").read_text()
    rendered = {v for group in item.rendered for v in group.versions}

    for version in rendered:
        assert f'value="../{version}/"' in page


def test_nav_lists_groups_but_not_aliases(built, builds):
    mkdocs = (REPO_ROOT / "mkdocs.yml").read_text()
    nav = mkdocs.split("nav:")[1].split("not_in_nav:")[0]

    for item in builds:
        for group in item.rendered:
            assert f"scenarios/{item.scenario.id}/{group.key}.md" in nav
            for version in group.versions:
                if version != group.key:
                    assert f"scenarios/{item.scenario.id}/{version}.md" not in nav


def test_design_notes_explain_the_colour_choices(built):
    """The colourblindness reasoning belongs where a reader sees it."""
    docs, _ = built
    notes = (docs / "design-notes.md").read_text().lower()

    assert "deuteranopia" in notes
    assert "colour is redundant" in notes or "redundant" in notes
    assert "traffic-light" in notes or "traffic light" in notes
    assert "wcag" in notes


def test_group_pages_say_what_identical_means(built, builds):
    """A group means 'this scenario cannot tell them apart', not 'pytest is
    identical'. The site must not overstate it."""
    docs, _ = built
    for item in builds:
        for group in item.rendered:
            if len(group) == 1:
                continue
            page = (docs / "scenarios" / item.scenario.id / f"{group.key}.md").read_text()
            assert "as far as this scenario can measure" in page


def test_retention_limits_rendering_not_storage(builds):
    for item in builds:
        assert len(item.rendered) <= len(item.groups)
        assert item.traces, "traces stay loaded regardless of what is rendered"


def test_stylesheet_and_core_pages_are_written(built):
    docs, _ = built
    for name in ("index.md", "versions.md", "changes.md", "design-notes.md"):
        assert (docs / name).exists()
    assert (docs / "assets" / "atlas.css").exists()


def test_scenario_source_is_linked_not_inlined(built, builds):
    """Scenarios grow directory trees; a collapsed code block does not scale.

    The repository renders the project better than the page can, so provenance
    links to it and names the files rather than dumping their contents.
    """
    docs, _ = built
    item = builds[0]
    page = (docs / "scenarios" / item.scenario.id / f"{item.latest.key}.md").read_text()

    assert item.scenario.source_url in page
    for source in item.scenario.source_files():
        assert source.name in page, "the file should still be named"
        body = source.read_text().strip().splitlines()
        longest = max(body, key=len)
        assert longest.strip() not in page, "file contents must not be inlined"


def test_heading_anchor_matches_python_markdown():
    """Anchors are computed here but resolved by python-markdown's slugifier.

    If the two disagree, every column link silently scrolls nowhere - so the
    real implementation is the oracle.
    """
    from markdown.extensions.toc import slugify

    from pytest_hook_atlas.build import heading_anchor

    for title in (
        "Startup and configuration",
        "Collection",
        "The run-test protocol",
        "Session finish",
        "A title, with punctuation!",
    ):
        assert heading_anchor(title) == slugify(title, "-")


def test_overview_columns_link_to_their_phase_headings(built, builds):
    """The overview doubles as a table of contents."""
    from pytest_hook_atlas import analysis
    from pytest_hook_atlas.build import heading_anchor

    docs, _ = built
    item = builds[0]
    page = (docs / "scenarios" / item.scenario.id / f"{item.latest.key}.md").read_text()

    linked = 0
    for phase in analysis.PHASES:
        heading = f"## {phase.title}"
        if heading not in page:
            continue
        anchor = heading_anchor(phase.title)
        assert f'xlink:href="#{anchor}"' in page, f"{phase.key} column is not clickable"
        linked += 1

    assert linked >= 3, "expected most phases present in the baseline scenario"
