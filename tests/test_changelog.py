"""Keep the changelog honest.

Recording changes is a habit that decays quietly. These tests make the decay
loud: bump the version without writing an entry and the suite fails.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest_hook_atlas

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def declared_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    return data["project"]["version"]


def released_versions() -> list[str]:
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(), re.MULTILINE)


def test_changelog_exists():
    assert CHANGELOG.exists()


def test_package_and_project_versions_agree():
    assert pytest_hook_atlas.__version__ == declared_version()


def test_the_current_version_has_a_changelog_entry():
    """A release without an entry is the failure mode this guards against."""
    assert declared_version() in released_versions()


def test_the_newest_entry_is_the_current_version():
    entries = released_versions()

    assert entries, "no released versions found in the changelog"
    assert entries[0] == declared_version(), "newest entry should be the current version"


def test_an_unreleased_section_is_kept_open():
    """Somewhere to write the next change down while it is still fresh."""
    assert "## [Unreleased]" in CHANGELOG.read_text()


def test_entries_are_dated():
    text = CHANGELOG.read_text()

    for version in released_versions():
        assert re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}", text, re.M)


def test_changelog_is_published_on_the_site(tmp_path):
    from pytest_hook_atlas import build

    docs = tmp_path / "docs"
    build.build(REPO_ROOT, docs, REPO_ROOT / "data" / "traces", verify_links=False)

    assert (docs / "changelog.md").exists()
    assert "Changelog: changelog.md" in (REPO_ROOT / "mkdocs.yml").read_text()
