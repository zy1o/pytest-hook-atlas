"""Tests for the ordered flow model.

The property that matters here is that *order* survives. An earlier design kept
only containment, which turned a sequence into an unordered fan-out.
"""

from __future__ import annotations

from hook_atlas import flow


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


# --------------------------------------------------------------------------
# folding long repetitive stretches


def loop(names_in_order, times):
    return [flow.FlowNode(name=name) for _ in range(times) for name in names_in_order]


def test_a_short_stretch_is_left_alone():
    """Folding is for stretches nobody can read, not for saving a few pixels."""
    nodes = loop(["a", "b"], 4)

    assert flow.fold_repetitive(nodes) == nodes


def test_one_cycle_survives_a_fold():
    """The reader must still see what the repetition is made of."""
    folded = flow.fold_repetitive(loop(["a", "b", "c"], 20))

    assert [node.name for node in folded[:3]] == ["a", "b", "c"]
    assert folded[3].is_summary
    assert folded[3].folded == ("a", "b", "c")
    assert "57 further steps" in folded[3].name


def test_a_hook_ending_the_stretch_twice_is_not_swallowed():
    """`pytest_testnodedown` fires once per worker, so it is not a singleton.

    It still ends the run rather than belonging to it. Recognised only by the
    singleton rule, it pinned the kept prefix to the whole stretch, nothing
    folded, and the controller drew at 14530pt.
    """
    nodes = [*loop(["a", "b"], 30), flow.FlowNode(name="down"), flow.FlowNode(name="down")]

    folded = flow.fold_repetitive(nodes)

    assert [node.name for node in folded[-2:]] == ["down", "down"]
    assert any(node.is_summary for node in folded)


def test_the_kept_prefix_is_bounded():
    """Covering every hook in a stretch is unbounded; the diagram is not."""
    nodes = [flow.FlowNode(name=f"h{index % 4}") for index in range(200)]
    nodes.insert(150, flow.FlowNode(name="h0"))

    folded = flow.fold_repetitive(nodes)

    assert len(folded) <= flow.FOLD_KEEP_MAX + 1, "prefix must stay bounded"
    assert any(node.is_summary for node in folded)


def test_a_hook_that_ends_the_stretch_is_not_swallowed():
    """pytest_collection_modifyitems closes collection; it is not the loop.

    Left inside the run it would also pin the representative prefix to the whole
    stretch, so nothing would fold at all.
    """
    folded = flow.fold_repetitive([*loop(["a", "b"], 20), flow.FlowNode(name="done")])

    assert folded[-1].name == "done"
    assert any(node.is_summary for node in folded)


def test_a_stretch_of_too_many_distinct_hooks_is_not_repetition():
    nodes = [flow.FlowNode(name=f"hook{index}") for index in range(30)]

    assert flow.fold_repetitive(nodes) == nodes


def test_folding_reaches_nested_steps():
    parent = flow.FlowNode(name="protocol", children=loop(["a", "b", "c"], 20))

    folded = flow.fold_repetitive([parent])

    assert folded[0].name == "protocol"
    assert any(child.is_summary for child in folded[0].children)


def test_a_summary_counts_the_steps_it_replaces():
    """A folded node stands for repeats as well as steps, so counts add up."""
    nodes = loop(["a", "b"], 20)
    nodes[-1].count = 5

    folded = flow.fold_repetitive(nodes)
    summary = next(node for node in folded if node.is_summary)
    kept = [node.name for node in folded if not node.is_summary]

    assert kept == ["a", "b"], "one cycle, then the summary"
    # 38 remaining nodes, one of which stands for five repeats
    assert summary.name.startswith("42 further steps")


def test_folding_stays_out_of_the_fingerprint():
    """Folding changes how a flow is drawn, never which releases share one page.

    The fingerprint is computed from the raw trace, so this is a guard against
    someone moving the fold down a layer to "clean up" the model.
    """
    import inspect

    from hook_atlas import grouping

    assert "fold_repetitive" not in inspect.getsource(grouping)
