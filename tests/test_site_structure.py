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
