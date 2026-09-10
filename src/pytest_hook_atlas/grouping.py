"""Group pytest versions whose captured flow is the same.

53 pytest releases would make 53 near-identical documents. Most releases change
nothing about the hook flow, so versions are grouped by a fingerprint of what
the page would actually say, and one document covers a range.

Two decisions here are load-bearing and easy to get wrong:

**The fingerprint is semantic, not rendered.** Hashing the rendered page would
group nothing, because documentation links are pinned per pytest version and so
every page differs by construction. The fingerprint covers the flow shape and
hook semantics only.

**Groups are named by their FIRST version.** Adding a scenario can only ever
split groups, never merge them - it refines the partition - so a version that
starts a group always starts a group. Naming by the last version instead would
silently change what an existing URL means: /flows/9.1.1/ covering 8.1.1-9.1.1
today would come to mean 9.1.0-9.1.1 tomorrow, and anyone who linked it would
land on different content. First-version naming makes new scenarios purely
additive.

Grouping is per scenario, deliberately. A scenario that cannot distinguish two
versions should say so, rather than inheriting split points from a scenario
that can - and it keeps adding a scenario from disturbing the others.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from packaging.version import Version

from . import analysis, flow

#: Hooks whose call pattern is bookkeeping rather than flow, excluded from the
#: fingerprint so they do not fragment the site. They are still *rendered* -
#: this only stops them creating new documents.
#:
#: ``pytest_plugin_registered`` fires once per registered plugin, so its count
#: tracks how many internal plugins a pytest release happens to ship. pytest
#: 8.3.5 and 8.4.0 differ by nothing else whatsoever (x34 vs x33), and that is
#: not a flow change anyone wants a separate document for.
#:
#: ``pytest_warning_recorded`` is deferred: _pytest/warnings.py wraps five hooks
#: with warnings.catch_warnings(record=True) and replays the whole batch from a
#: finally block once the wrapped phase ends. So its position marks a phase
#: boundary rather than where a warning arose, and its count depends on whatever
#: happened to warn - installed plugins, Python-version deprecations, the test
#: code itself. Neither is a property of the pytest release being documented.
BOOKKEEPING_HOOKS = frozenset({"pytest_plugin_registered", "pytest_warning_recorded"})

FINGERPRINT_LENGTH = 12


@dataclass(frozen=True)
class Group:
    """A run of consecutive pytest versions that produced the same flow."""

    fingerprint: str
    versions: tuple[str, ...]

    @property
    def key(self) -> str:
        """URL-stable identity: the version the flow first appeared in."""
        return self.versions[0]

    @property
    def newest(self) -> str:
        """Latest version in the group; its docs are the ones worth linking to."""
        return self.versions[-1]

    @property
    def label(self) -> str:
        if len(self.versions) == 1:
            return f"pytest {self.versions[0]}"
        return f"pytest {self.versions[0]} - {self.versions[-1]}"

    def __len__(self) -> int:
        return len(self.versions)


def _shape(nodes: list[flow.FlowNode]) -> list:
    """Flow structure with bookkeeping hooks removed, counts kept."""
    return [
        [node.name, node.count, _shape(node.children)]
        for node in nodes
        if node.name not in BOOKKEEPING_HOOKS
    ]


def fingerprint(trace: dict[str, Any]) -> str:
    """Hash of everything that would make two versions' pages differ."""
    phases = []
    for phase in analysis.PHASES:
        variants = flow.phase_variants(analysis.find_subtrees(trace["calls"], phase.anchors))
        phases.append([phase.key, [_shape(variant.flow) for variant in variants]])

    semantics = {
        name: [bool(spec.get("historic")), bool(spec.get("firstresult"))]
        for name, spec in trace.get("hookspecs", {}).items()
    }
    payload = json.dumps({"phases": phases, "hookspecs": semantics}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:FINGERPRINT_LENGTH]


def group_versions(fingerprints: dict[str, str]) -> list[Group]:
    """Collapse ``{version: fingerprint}`` into consecutive runs, oldest first.

    Only *consecutive* versions merge. If a flow changes and later reverts - as
    pytest did across 8.1.0 and 8.1.1 - those stay separate groups, because
    collapsing them would imply a continuity that did not exist.
    """
    if not fingerprints:
        return []

    ordered = sorted(fingerprints, key=Version)
    groups: list[list[str]] = [[ordered[0]]]
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if fingerprints[current] == fingerprints[previous]:
            groups[-1].append(current)
        else:
            groups.append([current])

    return [Group(fingerprint=fingerprints[g[0]], versions=tuple(g)) for g in groups]


def retain(groups: list[Group], major_versions: int) -> list[Group]:
    """Keep only groups whose newest version is in the last N pytest majors.

    Retention governs what is *rendered*, never what is stored: every trace
    stays committed, so a dropped group can be brought back by changing this
    number and rebuilding.
    """
    if not groups:
        return []
    majors = sorted({Version(group.newest).major for group in groups}, reverse=True)
    keep = set(majors[:major_versions])
    return [group for group in groups if Version(group.newest).major in keep]
