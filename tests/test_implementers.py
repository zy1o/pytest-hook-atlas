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
    """A trace whose only content is who implements what.

    Implementations are listed in pluggy's storage order, which is the reverse
    of call order, so helpers here reverse to match what pluggy would hand us.
    """
    return {
        "calls": [
            {
                "name": hook,
                "impls": [
                    {"plugin": p, "module": f"_pytest.{p}", "function": hook}
                    for p in reversed(plugins)
                ],
                "children": [],
            }
            for hook, plugins in plugins_by_hook.items()
        ],
        "hookspecs": {},
    }


def names(info):
    return tuple(item.plugin for item in info.current)


def test_identical_releases_collapse_to_one_run():
    traces = {v: trace_with({"pytest_configure": ["a", "b"]}) for v in ("8.0.0", "8.0.1")}

    info = implementers.reconcile(traces, ("8.0.0", "8.0.1"))["pytest_configure"]

    assert info.stable
    assert names(info) == ("a", "b")
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
    assert names(info) == ("fixtures",)
    assert [run.label for run in info.runs] == ["8.1.1 - 8.1.2", "8.2.0"]
    assert info.deltas() == [("8.2.0", ("_pytest.fixtures",), ("_pytest.python",))]


def test_a_reverted_change_does_not_merge_runs():
    traces = {
        "1.0.0": trace_with({"h": ["a"]}),
        "1.1.0": trace_with({"h": ["b"]}),
        "1.2.0": trace_with({"h": ["a"]}),
    }

    info = implementers.reconcile(traces, ("1.0.0", "1.1.0", "1.2.0"))["h"]

    assert len(info.runs) == 3


def test_ordering_alone_does_not_split_a_run():
    """Runs compare as sets; the run still reports the newest call order."""
    traces = {
        "1.0.0": trace_with({"h": ["b", "a"]}),
        "1.1.0": trace_with({"h": ["a", "b"]}),
    }

    info = implementers.reconcile(traces, ("1.0.0", "1.1.0"))["h"]

    assert info.stable
    assert names(info) == ("a", "b")


def test_missing_versions_are_ignored():
    traces = {"1.0.0": trace_with({"h": ["a"]})}

    info = implementers.reconcile(traces, ("1.0.0", "9.9.9"))["h"]

    assert names(info) == ("a",)


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
    assert "fixtures" in names(info)
    assert "python" not in names(info)
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


def test_call_order_is_pluggys_execution_order_not_its_storage_order():
    """pluggy stores hook_impls reversed and iterates them with reversed().

    A trylast implementation therefore sits at index 0 of the stored list.
    Rendering that order verbatim showed the table upside down.
    """
    trace = {
        "calls": [
            {
                "name": "pytest_runtest_setup",
                "impls": [
                    {"plugin": "last", "module": "m", "function": "pytest_runtest_setup"},
                    {"plugin": "middle", "module": "m", "function": "pytest_runtest_setup"},
                    {"plugin": "first", "module": "m", "function": "pytest_runtest_setup"},
                ],
                "children": [],
            }
        ],
        "hookspecs": {},
    }

    info = implementers.reconcile({"1.0.0": trace}, ("1.0.0",))["pytest_runtest_setup"]

    assert [item.plugin for item in info.current] == ["first", "middle", "last"]


def test_real_traces_run_wrappers_before_trylast():
    """A sanity check against pluggy's documented ordering rules."""
    build = build_module.collect(REPO_ROOT, REPO_ROOT / "data" / "traces")[0]
    group = build.groups[-1]
    info = implementers.reconcile(build.traces, group.versions)["pytest_runtest_setup"]
    order = [item.plugin for item in info.current]

    assert order.index("logging-plugin") < order.index("runner")
    assert order.index("runner") < order.index("threadexception")


def test_owner_strips_the_hook_name_and_keeps_the_class():
    assert (
        implementers._owner(
            {"module": "_pytest.capture", "function": "CaptureManager.pytest_runtest_setup"},
            "pytest_runtest_setup",
        )
        == "_pytest.capture.CaptureManager"
    )
    assert (
        implementers._owner(
            {"module": "_pytest.runner", "function": "pytest_runtest_setup"},
            "pytest_runtest_setup",
        )
        == "_pytest.runner"
    )


def test_label_adds_the_registered_name_only_when_it_differs():
    plain = implementers.Implementation(plugin="runner", owner="_pytest.runner")
    renamed = implementers.Implementation(
        plugin="logging-plugin", owner="_pytest.logging.LoggingPlugin"
    )

    assert plain.label == "_pytest.runner"
    assert renamed.label == "_pytest.logging.LoggingPlugin (logging-plugin)"


def test_deltas_name_the_module_not_just_the_plugin():
    """ "gained _pytest.unraisableexception" says where to look; "gained
    unraisableexception" only says what it is called."""
    build = build_module.collect(REPO_ROOT, REPO_ROOT / "data" / "traces")[0]
    group = next(g for g in build.groups if len(g) > 10)
    info = implementers.reconcile(build.traces, group.versions)["pytest_configure"]

    gained = [name for _, gains, _ in info.deltas() for name in gains]

    assert gained, "expected pytest_configure to gain implementers in this range"
    assert all(name.startswith("_pytest.") for name in gained), gained


def test_pytest_own_plugins_are_classified_as_internal():
    internal = implementers.Implementation(plugin="runner", owner="_pytest.runner")
    nested = implementers.Implementation(
        plugin="capturemanager", owner="_pytest.capture.CaptureManager"
    )

    assert internal.internal
    assert nested.internal


def test_a_conftest_and_third_party_plugins_are_external():
    """These are what someone debugging their own suite came to see."""
    conftest = implementers.Implementation(plugin="conftest.py", owner="conftest")
    third_party = implementers.Implementation(plugin="xdist", owner="xdist.plugin")

    assert not conftest.internal
    assert not third_party.internal


def test_a_module_merely_starting_with_pytest_is_not_internal():
    """pytest_subtests is a third-party distribution, not part of pytest."""
    plugin = implementers.Implementation(plugin="subtests", owner="pytest_subtests.plugin")

    assert not plugin.internal
