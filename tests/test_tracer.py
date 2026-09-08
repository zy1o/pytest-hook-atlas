"""Tests for the pluggy-based hook tracer."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from pytest_hook_atlas import tracer

SAMPLE_PROJECT = """
import pytest


@pytest.fixture
def thing():
    yield "thing"


@pytest.mark.parametrize("n", range(3))
def test_pass(n, thing):
    assert True


def test_fail():
    assert False
"""


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.get("children", []))


@pytest.fixture(scope="module")
def trace(tmp_path_factory) -> dict:
    """Run a real pytest session under the tracer and return the parsed trace."""
    project = tmp_path_factory.mktemp("project")
    (project / "test_sample.py").write_text(SAMPLE_PROJECT)
    destination = project / "trace.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "pytest_hook_atlas.tracer",
            str(project),
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=project,
        env={
            **os.environ,
            "HOOK_ATLAS_TRACE": str(destination),
            "HOOK_ATLAS_SCENARIO": "unit-test",
        },
        capture_output=True,
        text=True,
    )
    assert destination.exists(), f"no trace written\n{result.stdout}\n{result.stderr}"
    return json.loads(destination.read_text())


def test_trace_records_environment_and_scenario(trace):
    assert trace["schema_version"] == tracer.SCHEMA_VERSION
    assert trace["environment"]["pytest"] == pytest.__version__
    assert trace["scenario"]["id"] == "unit-test"


def test_call_tree_is_well_formed(trace):
    """No desyncs means every ``before`` was matched by its ``after``."""
    assert trace["desyncs"] == []
    assert trace["stats"]["total_calls"] > 100

    for node in _walk(trace["calls"]):
        for child in node.get("children", []):
            assert child["depth"] == node["depth"] + 1
            assert child["seq"] > node["seq"]


def test_nesting_reflects_real_pytest_structure(trace):
    """The runtest protocol must appear *inside* the run loop, not beside it."""
    by_name = {node["name"]: node for node in _walk(trace["calls"])}
    assert "pytest_runtestloop" in by_name

    loop_children = set(_names(by_name["pytest_runtestloop"]))
    assert "pytest_runtest_protocol" in loop_children
    assert "pytest_runtest_setup" in loop_children
    assert "pytest_runtest_call" in loop_children
    assert "pytest_runtest_teardown" in loop_children


def _names(node):
    for child in _walk(node.get("children", [])):
        yield child["name"]


def test_records_which_plugin_supplied_each_implementation(trace):
    """Provenance is the thing the old log-scraping approach could never see."""
    impls = [impl for node in _walk(trace["calls"]) for impl in node["impls"]]
    assert impls

    plugins = {impl["plugin"] for impl in impls}
    assert any(name and "runner" in str(name) for name in plugins)
    assert all("wrapper" in impl and "plugin" in impl for impl in impls)


def test_prologue_matches_documented_boundary(trace):
    """Guards the documented capture boundary against pytest upgrades."""
    traced = {node["name"] for node in _walk(trace["calls"])}

    for hook in tracer.PROLOGUE_HOOKS:
        assert hook not in traced, f"{hook} is capturable now; shrink PROLOGUE_HOOKS"

    # the earliest hooks we *do* capture - these bound the prologue from above
    for hook in ("pytest_load_initial_conftests", "pytest_plugin_registered"):
        assert hook in traced, f"{hook} slipped into the prologue"


def test_historic_hooks_replay_for_late_registered_plugins(tmp_path):
    """A conftest implementing a historic hook makes it reappear in the trace.

    This documents why PROLOGUE_HOOKS is about *original* invocations: the
    replay is captured, the original never is.
    """
    (tmp_path / "test_x.py").write_text("def test_x():\n    assert True\n")
    (tmp_path / "conftest.py").write_text(
        "def pytest_addoption(parser, pluginmanager):\n    pass\n"
    )
    destination = tmp_path / "trace.json"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "pytest_hook_atlas.tracer",
            str(tmp_path),
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=tmp_path,
        env={**os.environ, "HOOK_ATLAS_TRACE": str(destination)},
        capture_output=True,
        text=True,
    )
    replayed = {node["name"] for node in _walk(json.loads(destination.read_text())["calls"])}

    assert "pytest_addoption" in replayed
    assert "pytest_addoption" in tracer.PROLOGUE_HOOKS


def test_hookspec_metadata_classifies_hook_semantics():
    metadata = tracer.hookspec_metadata()

    assert metadata["pytest_configure"]["historic"] is True
    assert metadata["pytest_runtest_setup"]["historic"] is False

    assert metadata["pytest_runtest_protocol"]["firstresult"] is True
    assert metadata["pytest_runtest_setup"]["firstresult"] is False

    assert metadata["pytest_collection_modifyitems"]["argnames"] == [
        "session",
        "config",
        "items",
    ]
    assert metadata["pytest_configure"]["summary"]


def test_recorder_builds_nested_tree_without_pytest():
    """Unit-level check of the before/after stack discipline."""
    recorder = tracer.HookRecorder()

    recorder.before("outer", [], {})
    recorder.before("inner", [], {})
    recorder.after(None, "inner", [], {})
    recorder.after(None, "outer", [], {})

    assert recorder.desyncs == []
    assert len(recorder.roots) == 1
    assert recorder.roots[0].name == "outer"
    assert [child.name for child in recorder.roots[0].children] == ["inner"]
    assert recorder.total_calls() == 2


def test_recorder_reports_desync_rather_than_crashing():
    recorder = tracer.HookRecorder()
    recorder.after(None, "never_started", [], {})

    assert recorder.desyncs
