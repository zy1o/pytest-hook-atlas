"""Tests for reconciling implementers across the releases a page covers.

The reconciliation exists because a page covers a *range*, and implementers can
differ across that range even when the flow does not - so rendering only the
newest release's answer would be quietly wrong for the rest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_hook_atlas import analysis, implementers
from pytest_hook_atlas import build as build_module

REPO_ROOT = Path(__file__).resolve().parent.parent


def trace_with(plugins_by_hook):
    """A trace whose only content is who implements what."""
    return {
        "calls": [
            {
                "name": hook,
                "impls": [{"plugin": p} for p in plugins],
                "children": [],
            }
            for hook, plugins in plugins_by_hook.items()
        ],
        "hookspecs": {},
    }


def test_identical_releases_collapse_to_one_run():
    traces = {v: trace_with({"pytest_configure": ["a", "b"]}) for v in ("8.0.0", "8.0.1")}

    info = implementers.reconcile(traces, ("8.0.0", "8.0.1"))["pytest_configure"]

    assert info.stable
    assert info.current == ("a", "b")
    assert info.changed_at is None


def test_a_change_splits_into_runs():
    traces = {
        "8.1.1": trace_with({"pytest_cmdline_main": ["python"]}),
        "8.1.2": trace_with({"pytest_cmdline_main": ["python"]}),
        "8.2.0": trace_with({"pytest_cmdline_main": ["fixtures"]}),
    }

    info = implementers.reconcile(traces, ("8.1.1", "8.1.2", "8.2.0"))["pytest_cmdline_main"]

    assert not info.stable
    assert info.changed_at == "8.2.0"
    assert info.current == ("fixtures",)
    assert [run.label for run in info.runs] == ["8.1.1 - 8.1.2", "8.2.0"]


def test_a_reverted_change_does_not_merge_runs():
    traces = {
        "1.0.0": trace_with({"h": ["a"]}),
        "1.1.0": trace_with({"h": ["b"]}),
        "1.2.0": trace_with({"h": ["a"]}),
    }

    info = implementers.reconcile(traces, ("1.0.0", "1.1.0", "1.2.0"))["h"]

    assert len(info.runs) == 3


def test_plugins_are_sorted_so_ordering_noise_does_not_split_runs():
    traces = {
        "1.0.0": trace_with({"h": ["b", "a"]}),
        "1.1.0": trace_with({"h": ["a", "b"]}),
    }

    assert implementers.reconcile(traces, ("1.0.0", "1.1.0"))["h"].stable


def test_missing_versions_are_ignored():
    traces = {"1.0.0": trace_with({"h": ["a"]})}

    info = implementers.reconcile(traces, ("1.0.0", "9.9.9"))["h"]

    assert info.current == ("a",)


def test_reconcile_of_nothing():
    assert implementers.reconcile({}, ()) == {}


@pytest.fixture(scope="module")
def real_build():
    return build_module.collect(REPO_ROOT, REPO_ROOT / "data" / "traces")[0]


def test_real_traces_show_pytest_moving_a_hookimpl(real_build):
    """pytest moved pytest_cmdline_main from the python plugin to fixtures at
    8.2.0 without changing the flow, so one page covers releases that disagree.
    """
    group = next(g for g in real_build.groups if "8.2.0" in g.versions)
    info = implementers.reconcile(real_build.traces, group.versions)["pytest_cmdline_main"]

    assert not info.stable
    assert info.changed_at == "8.2.0"
    assert "fixtures" in info.current
    assert "python" not in info.current
    assert "python" in info.runs[0].plugins


def test_every_hook_in_a_group_is_reconciled(real_build):
    for group in real_build.groups:
        reconciled = implementers.reconcile(real_build.traces, group.versions)
        observed = set(analysis.full_graph(real_build.traces[group.newest]).hooks)

        assert observed <= set(reconciled)
        for info in reconciled.values():
            assert info.runs, f"{info.hook} has no runs"
            covered = [v for run in info.runs for v in run.versions]
            assert covered == [v for v in group.versions if v in real_build.traces]
