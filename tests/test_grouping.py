"""Tests for grouping pytest versions by identical flow.

The URL-stability property here is the important one: it is what stops a
published link silently coming to mean something else.
"""

from __future__ import annotations

from pathlib import Path

from hook_atlas import grouping

from pytest_hook_atlas import matrix, scenarios
from pytest_hook_atlas.build import _fingerprint as fingerprint

#: Grouping is generic; what a fingerprint *means* is pytest's business - its
#: phases and its bookkeeping hooks. These assert pytest's answer, so they go
#: through the same helper the build does.


def trace(calls, hookspecs=None):
    return {
        "calls": calls,
        "hookspecs": hookspecs
        or {"pytest_runtest_protocol": {"historic": False, "firstresult": True}},
    }


def node(name, children=()):
    return {"name": name, "impls": [], "children": list(children)}


def repeat(name, times):
    """Repeat counts are derived from consecutive siblings by flow.collapse,
    so a repeat has to be expressed as actual repetition, not a count field."""
    return [node(name) for _ in range(times)]


def protocol(children):
    return node("pytest_runtest_protocol", children)


def test_fingerprint_is_stable_for_identical_traces():
    calls = [protocol([node("pytest_runtest_setup")])]

    assert fingerprint(trace(calls)) == fingerprint(trace(calls))


def test_fingerprint_changes_when_the_flow_changes():
    a = fingerprint(trace([protocol([node("pytest_runtest_setup")])]))
    b = fingerprint(trace([protocol([node("pytest_runtest_call")])]))

    assert a != b


def test_bookkeeping_hooks_do_not_change_the_fingerprint():
    """pytest 8.3.5 and 8.4.0 differ only by plugin_registered's count.

    That tracks how many internal plugins a release ships, not the flow being
    documented, and must not create a separate document.
    """
    plain = trace([protocol([node("pytest_runtest_setup")])])
    noisy = trace(
        [
            protocol(
                [
                    *repeat("pytest_plugin_registered", 37),
                    node("pytest_runtest_setup"),
                    *repeat("pytest_warning_recorded", 5),
                ]
            )
        ]
    )

    assert fingerprint(plain) == fingerprint(noisy)


def test_bookkeeping_count_differences_are_ignored():
    def with_count(n):
        return trace([protocol([*repeat("pytest_plugin_registered", n), node("x")])])

    assert fingerprint(with_count(34)) == fingerprint(with_count(33))


def test_non_bookkeeping_counts_still_matter():
    def with_count(n):
        return trace([protocol(repeat("pytest_runtest_setup", n))])

    assert fingerprint(with_count(1)) != fingerprint(with_count(2))


def test_consecutive_versions_with_one_fingerprint_form_a_group():
    groups = grouping.group_versions(
        {"8.0.0": "a", "8.0.1": "a", "8.0.2": "a"}, application="pytest"
    )

    assert len(groups) == 1
    assert groups[0].versions == ("8.0.0", "8.0.1", "8.0.2")
    assert groups[0].label == "pytest 8.0.0 - 8.0.2"


def test_a_reverted_flow_does_not_rejoin_its_earlier_group():
    """pytest did exactly this across 8.1.0 and 8.1.1; merging would imply a
    continuity that never existed."""
    groups = grouping.group_versions({"8.0.0": "a", "8.1.0": "b", "8.1.1": "a"})

    assert [g.versions for g in groups] == [("8.0.0",), ("8.1.0",), ("8.1.1",)]


def test_groups_are_named_by_their_first_version():
    """URL stability. Adding a scenario only ever splits groups, so a version
    that starts a group always starts a group - naming by the last version
    would silently change what an existing URL means."""
    coarse = grouping.group_versions({"8.1.1": "a", "8.4.2": "a", "9.0.0": "a"})
    refined = grouping.group_versions({"8.1.1": "a", "8.4.2": "a", "9.0.0": "b"})

    assert coarse[0].key == "8.1.1"
    assert refined[0].key == "8.1.1"
    assert {g.key for g in coarse} <= {g.key for g in refined}
    assert refined[-1].key == "9.0.0"


def test_group_versions_sorts_by_version_not_string():
    groups = grouping.group_versions({"8.10.0": "a", "8.9.0": "a"})

    assert groups[0].versions == ("8.9.0", "8.10.0")


def test_group_versions_of_nothing():
    assert grouping.group_versions({}) == []


def test_retention_keeps_the_last_n_majors():
    groups = grouping.group_versions({"6.0.0": "a", "7.0.0": "b", "8.0.0": "c", "9.0.0": "d"})
    kept = grouping.retain(groups, 2)

    assert [g.newest for g in kept] == ["8.0.0", "9.0.0"]


def test_retention_never_deletes_traces_only_limits_rendering():
    groups = grouping.group_versions({"6.0.0": "a", "9.0.0": "b"})

    assert len(grouping.retain(groups, 1)) == 1
    assert len(grouping.retain(groups, 9)) == 2


def test_adding_a_scenario_marks_existing_versions_as_incomplete(tmp_path):
    """Regression: capture-missing keyed on version alone reported "nothing to
    capture" after a scenario was added, silently skipping its backfill."""
    (tmp_path / "9.1.1").mkdir()
    (tmp_path / "9.1.1" / "baseline.json").write_text("{}")

    one = [scenarios.Scenario("baseline", "b", "", "", (), tmp_path)]
    two = [*one, scenarios.Scenario("xdist", "x", "", "", (), tmp_path)]

    assert matrix.captured_versions(tmp_path, one) == {"9.1.1"}
    assert matrix.captured_versions(tmp_path, two) == set()


def test_captured_pairs_reports_version_and_scenario(tmp_path):
    (tmp_path / "9.1.1").mkdir()
    (tmp_path / "9.1.1" / "baseline.json").write_text("{}")
    (tmp_path / "9.1.1" / "every-hook-conftest.json").write_text("{}")

    assert matrix.captured_pairs(tmp_path) == {
        ("9.1.1", "baseline"),
        ("9.1.1", "every-hook-conftest"),
    }


def test_real_traces_group_into_stable_urls():
    """End-to-end against the committed traces."""
    root = Path(__file__).resolve().parent.parent / "data" / "traces"
    from pytest_hook_atlas import analysis

    fingerprints = {
        d.name: fingerprint(analysis.load_trace(d / "baseline.json"))
        for d in root.iterdir()
        if (d / "baseline.json").exists()
    }
    groups = grouping.group_versions(fingerprints)

    assert len(groups) >= 2
    assert all(g.key == g.versions[0] for g in groups)
    assert len({g.key for g in groups}) == len(groups)
