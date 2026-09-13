"""The ordered flow model.

The trace records both *containment* (which hook was called inside which) and
*order* (the sequence siblings were called in). An earlier version of this
project drew only containment, which produced a star of unordered boxes rather
than a flow - it hid the thing that actually confuses people, namely that
setup, call and teardown are each followed by their own makereport/logreport
pair.

This module keeps both. Consecutive siblings with an identical shape collapse
into one element carrying a repeat count, so a run of eight tests reads as one
step marked "x8" instead of eight copies.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FlowNode:
    """One step in the flow, possibly repeated, possibly containing more steps."""

    name: str
    count: int = 1
    children: list[FlowNode] = field(default_factory=list)

    #: When set, this node is a summary standing in for a long stretch of
    #: steps drawn from these few hooks, rather than a hook call itself.
    folded: tuple[str, ...] = ()

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def is_summary(self) -> bool:
        return bool(self.folded)


def signature(node: dict[str, Any]) -> tuple:
    """Structural fingerprint used to decide whether two calls look the same."""
    return (node["name"], tuple(signature(child) for child in node.get("children", [])))


def collapse(nodes: list[dict[str, Any]]) -> list[FlowNode]:
    """Convert raw trace nodes to flow nodes, merging consecutive repeats.

    Only *consecutive* identical siblings merge. Two runs of the same shape
    separated by something different stay separate, because the thing in
    between is usually the interesting part.
    """
    flow: list[FlowNode] = []
    previous_signature = None

    for node in nodes:
        current = signature(node)
        if flow and current == previous_signature:
            flow[-1].count += 1
            continue
        flow.append(FlowNode(name=node["name"], children=collapse(node.get("children", []))))
        previous_signature = current

    return flow


def total_steps(nodes: list[FlowNode]) -> int:
    return sum(1 + total_steps(node.children) for node in nodes)


@dataclass
class Variant:
    """One distinct shape an anchor hook's subtree took, and how often."""

    flow: list[FlowNode]
    count: int
    added: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def differs(self) -> bool:
        return bool(self.added or self.missing)


def _hook_names(nodes: list[FlowNode]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        names.add(node.name)
        names |= _hook_names(node.children)
    return names


def group_variants(occurrences: list[dict[str, Any]]) -> list[Variant]:
    """Group occurrences by shape, most common first.

    Rendering every occurrence produces an unreadably tall diagram; rendering
    only the first hides that a failing or skipped test takes a different path.
    So: draw the most common shape, and describe the others as deltas against it.
    """
    if not occurrences:
        return []

    grouped: dict[tuple, list[dict[str, Any]]] = {}
    for occurrence in occurrences:
        grouped.setdefault(signature(occurrence), []).append(occurrence)

    variants = [
        Variant(flow=collapse([members[0]]), count=len(members)) for members in grouped.values()
    ]
    variants.sort(key=lambda variant: variant.count, reverse=True)

    baseline = _hook_names(variants[0].flow)
    for variant in variants[1:]:
        names = _hook_names(variant.flow)
        variant.added = sorted(names - baseline)
        variant.missing = sorted(baseline - names)
    return variants


def phase_variants(subtrees: list[dict[str, Any]]) -> list[Variant]:
    """Variants for a repeated hook, or one combined sequence for distinct ones.

    A phase anchored on several different hooks (startup, say) is a single
    sequence and must not be split into "variants"; a phase anchored on one
    hook that ran many times (the runtest protocol) genuinely has variants.
    """
    if not subtrees:
        return []
    if len({node["name"] for node in subtrees}) > 1:
        return [Variant(flow=collapse(subtrees), count=1)]
    return group_variants(subtrees)


def prune(nodes: list[FlowNode], max_depth: int) -> list[FlowNode]:
    """Copy the flow, dropping anything deeper than ``max_depth`` levels.

    Used for the session outline: the whole run is ~110 steps, which is too
    tall to read, but its top two levels are the shape of a pytest session.
    """
    if max_depth <= 0:
        return []
    return [
        FlowNode(
            name=node.name,
            count=node.count,
            children=prune(node.children, max_depth - 1),
        )
        for node in nodes
    ]


#: A stretch at least this long, drawing on no more than this many distinct
#: hooks, is a candidate for folding when rendering. The threshold is
#: deliberately high: a dozen steps are worth reading, ninety are not, and
#: folding too eagerly would hide the handful of xdist hooks that make the
#: controller's startup worth looking at in the first place.
FOLD_MIN_RUN = 20
FOLD_MAX_DISTINCT = 5

#: Fold only if at least this many steps would actually disappear. Replacing
#: four steps with a box saying "four steps happened" helps nobody.
FOLD_MIN_SAVING = 4

#: Never keep more than this many steps of a folded stretch drawn. Without a
#: bound, one hook appearing late in a long stretch keeps the whole thing.
FOLD_KEEP_MAX = 24


def _cycle(nodes: list[FlowNode], cap: int = FOLD_KEEP_MAX) -> int:
    """How much of the stretch to keep drawn: enough to show every hook in it.

    Bounded, and that bound is the whole point. Asking only for "every name once"
    is unbounded: under `--dist each` the controller's report traffic ends with
    two `pytest_testnodedown` calls, which dragged the prefix to the end of a
    188-step stretch, left nothing to fold and drew a 14530pt diagram. Cutting
    instead at the first repeat is bounded but too blunt - it threw away the
    nested `collect_file` -> `pycollect_makemodule` structure that makes a
    worker's collection worth looking at.

    So: cover what is there, up to a readable number of steps.
    """
    outstanding = {node.name for node in nodes}
    for position, node in enumerate(nodes[:cap], start=1):
        outstanding.discard(node.name)
        if not outstanding:
            return position
    return min(cap, len(nodes))


def fold_repetitive(
    nodes: list[FlowNode],
    min_run: int = FOLD_MIN_RUN,
    max_distinct: int = FOLD_MAX_DISTINCT,
) -> list[FlowNode]:
    """Fold the middle of long stretches that only shuffle a handful of hooks.

    Under xdist the controller's run loop is hundreds of steps of results
    arriving from workers - logstart, logreport, report_from_serializable,
    logfinish - in an order that depends on which worker finished first. It
    collapses to nothing, because consecutive steps are rarely identical, and
    renders as thousands of pixels of noise that says only "reports came back".

    One turn of the loop is drawn in full, and whatever follows the loop stays
    drawn too; only the repetition between them is summarised. Applied when
    rendering, never in the fingerprint: this changes how a flow is *drawn*, and
    must not change which releases are judged to share a flow.
    """
    folded: list[FlowNode] = []
    index = 0
    while index < len(nodes):
        run_end, seen = index, set()
        while run_end < len(nodes):
            candidate = seen | {nodes[run_end].name}
            if len(candidate) > max_distinct:
                break
            seen = candidate
            run_end += 1

        # Whatever follows the loop is not the loop: `pytest_testnodedown`
        # closing the run, `pytest_collection_modifyitems` closing collection.
        # Those are worth drawing, so they are trimmed off the stretch and left
        # alone - twice, because the two ways of recognising them catch
        # different things. A hook appearing once is one; and after the cycle is
        # known, so is anything trailing that the cycle never used.
        run = nodes[index:run_end]
        occurrences = Counter(node.name for node in run)
        while run and occurrences[run[-1].name] == 1:
            occurrences[run.pop().name] -= 1

        keep = _cycle(run)
        body = {node.name for node in run[:keep]}
        while run and run[-1].name not in body:
            run.pop()

        tail = run[keep:]
        steps = sum(node.count for node in tail)
        if len(run) >= min_run and len(body) > 1 and steps >= FOLD_MIN_SAVING:
            folded.extend(fold_repetitive(run[:keep], min_run, max_distinct))
            names = tuple(sorted({node.name for node in tail}))
            plural = "" if len(names) == 1 else "s"
            folded.append(
                FlowNode(
                    name=f"{steps} further steps of {len(names)} hook{plural}",
                    folded=names,
                )
            )
            index += len(run)
            continue

        node = nodes[index]
        folded.append(
            FlowNode(
                name=node.name,
                count=node.count,
                children=fold_repetitive(node.children, min_run, max_distinct),
            )
        )
        index += 1
    return folded
