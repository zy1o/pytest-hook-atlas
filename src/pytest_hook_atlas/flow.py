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

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FlowNode:
    """One step in the flow, possibly repeated, possibly containing more steps."""

    name: str
    count: int = 1
    children: list[FlowNode] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children


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
