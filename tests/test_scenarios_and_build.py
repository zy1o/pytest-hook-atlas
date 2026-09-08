"""Tests for scenario discovery and site generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pytest_hook_atlas import analysis, build, scenarios

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def discovered():
    return scenarios.discover(REPO_ROOT / "scenarios")


def test_scenarios_are_discovered_in_declared_order(discovered):
    assert [scenario.id for scenario in discovered][:1] == ["baseline"]
    assert all(scenario.title for scenario in discovered)


def test_every_scenario_links_to_its_own_source(discovered):
    """The site must always be able to show the code behind a diagram."""
    for scenario in discovered:
        assert scenario.source_url.endswith(f"/scenarios/{scenario.id}")
        assert scenario.source_files(), f"{scenario.id} has no source files to show"


def test_scenario_metadata_excludes_the_toml_itself(discovered):
    for scenario in discovered:
        assert all(path.name != "scenario.toml" for path in scenario.source_files())


@pytest.fixture(scope="module")
def captured(tmp_path_factory, discovered):
    workdir = tmp_path_factory.mktemp("work")
    destination = tmp_path_factory.mktemp("traces")
    scenario = discovered[0]
    path = scenarios.capture(scenario, destination / f"{scenario.id}.json", workdir)
    return scenario, analysis.load_trace(path)


def test_capture_produces_a_usable_trace(captured):
    _, trace = captured

    assert trace["desyncs"] == []
    assert trace["stats"]["total_calls"] > 50
    assert trace["scenario"]["id"] == "baseline"


def test_build_writes_pages_and_assets(captured, tmp_path):
    scenario, trace = captured
    traces_dir = tmp_path / "traces"
    traces_dir.mkdir()
    (traces_dir / f"{scenario.id}.json").write_text(json.dumps(trace))

    docs = tmp_path / "docs"
    pages = build.build(REPO_ROOT, docs, traces_dir)

    assert (docs / "index.md").exists()
    assert (docs / "scenarios" / f"{scenario.id}.md").exists()
    assert (docs / "assets" / f"{scenario.id}-full.svg").exists()
    assert len(pages) >= 2


def test_scenario_page_carries_provenance(captured, tmp_path):
    """A reader must be able to get from a diagram to the code behind it."""
    scenario, trace = captured
    page = build.scenario_page(scenario, trace, tmp_path)

    assert scenario.source_url in page
    assert "## How this was produced" in page
    assert "```mermaid" in page
    for source in scenario.source_files():
        assert source.name in page


def test_index_lists_every_scenario(captured):
    scenario, trace = captured
    page = build.index_page([(scenario, trace)])

    assert f"scenarios/{scenario.id}.md" in page
    assert "How to read the diagrams" in page
