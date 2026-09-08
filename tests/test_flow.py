"""Tests for the ordered flow model.

The property that matters here is that *order* survives. An earlier design kept
only containment, which turned a sequence into an unordered fan-out.
"""

from __future__ import annotations

from pytest_hook_atlas import flow


def raw(name, children=()):
    return {"name": name, "children": [dict(c) for c in children]}


def names(nodes):
    return [(node.name, node.count) for node in nodes]


def test_consecutive_identical_siblings_collapse_with_a_count():
    collapsed = flow.collapse([raw("a"), raw("a"), raw("a"), raw("b")])

    assert names(collapsed) == [("a", 3), ("b", 1)]


def test_non_consecutive_repeats_stay_separate():
    """The thing in between is usually the interesting part."""
    collapsed = flow.collapse([raw("a"), raw("b"), raw("a")])

    assert names(collapsed) == [("a", 1), ("b", 1), ("a", 1)]


def test_nodes_with_different_children_do_not_collapse():
    collapsed = flow.collapse([raw("a", [raw("x")]), raw("a", [raw("y")])])

    assert names(collapsed) == [("a", 1), ("a", 1)]


def test_order_is_preserved():
    collapsed = flow.collapse([raw("first"), raw("second"), raw("third")])

    assert [node.name for node in collapsed] == ["first", "second", "third"]


def test_nesting_is_preserved():
    collapsed = flow.collapse([raw("outer", [raw("inner")])])

    assert collapsed[0].children[0].name == "inner"
    assert not collapsed[0].is_leaf
    assert collapsed[0].children[0].is_leaf


def test_prune_limits_depth():
    nested = flow.collapse([raw("a", [raw("b", [raw("c")])])])

    assert flow.total_steps(nested) == 3
    assert flow.total_steps(flow.prune(nested, 2)) == 2
    assert flow.prune(nested, 1)[0].children == []


def test_group_variants_orders_by_frequency_and_diffs_against_the_common_one():
    common = raw("p", [raw("setup"), raw("call")])
    odd = raw("p", [raw("setup"), raw("call"), raw("exception_interact")])
    variants = flow.group_variants([common, dict(common), dict(common), odd])

    assert variants[0].count == 3
    assert not variants[0].differs
    assert variants[1].count == 1
    assert variants[1].added == ["exception_interact"]
    assert variants[1].missing == []


def test_group_variants_reports_missing_steps():
    common = raw("p", [raw("setup"), raw("call")])
    skipped = raw("p", [raw("setup")])
    variants = flow.group_variants([common, dict(common), skipped])

    assert variants[1].missing == ["call"]


def test_phase_variants_keeps_distinct_anchors_as_one_sequence():
    """A phase spanning several different hooks is a sequence, not variants."""
    variants = flow.phase_variants([raw("configure"), raw("sessionstart")])

    assert len(variants) == 1
    assert [node.name for node in variants[0].flow] == ["configure", "sessionstart"]


def test_phase_variants_splits_a_repeated_anchor():
    variants = flow.phase_variants([raw("p", [raw("a")]), raw("p", [raw("b")])])

    assert len(variants) == 2


def test_phase_variants_of_nothing():
    assert flow.phase_variants([]) == []
