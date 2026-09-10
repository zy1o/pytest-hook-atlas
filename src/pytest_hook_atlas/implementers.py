"""Reconcile which plugins implement each hook across a group of releases.

Every trace already records the plugins behind each hook call, so this needs no
new capture - it reads what is committed. The work is reconciliation: a page
covers a *range* of pytest releases, and implementers can differ across that
range even when the flow does not.

That happens. In the baseline scenario, ``pytest_cmdline_main`` moved from the
``python`` plugin to ``fixtures`` at pytest 8.2.0 without changing the flow at
all, so one page covers releases that disagree. Rendering only the newest
release's answer would have been quietly wrong for the other nineteen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import analysis


@dataclass(frozen=True)
class Run:
    """A stretch of consecutive releases agreeing on who implements a hook."""

    versions: tuple[str, ...]
    plugins: tuple[str, ...]

    @property
    def label(self) -> str:
        if len(self.versions) == 1:
            return self.versions[0]
        return f"{self.versions[0]} - {self.versions[-1]}"


@dataclass(frozen=True)
class HookImplementers:
    """Who implements one hook, across the releases a page covers."""

    hook: str
    runs: tuple[Run, ...]

    @property
    def stable(self) -> bool:
        """True when every release in the range agrees."""
        return len(self.runs) <= 1

    @property
    def current(self) -> tuple[str, ...]:
        """The newest release's answer, which is what the diagrams reflect."""
        return self.runs[-1].plugins if self.runs else ()

    @property
    def changed_at(self) -> str | None:
        """The release the newest answer first applied from, if it changed."""
        if self.stable:
            return None
        return self.runs[-1].versions[0]


def _plugins_by_hook(trace: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    graph = analysis.full_graph(trace)
    return {name: tuple(sorted(hook.plugins)) for name, hook in graph.hooks.items()}


def reconcile(
    traces: dict[str, dict[str, Any]], versions: tuple[str, ...]
) -> dict[str, HookImplementers]:
    """Collapse per-release implementer sets into runs, oldest first.

    ``versions`` must already be in release order - it comes from a group, which
    is built that way.
    """
    per_version = {
        version: _plugins_by_hook(traces[version]) for version in versions if version in traces
    }
    if not per_version:
        return {}

    ordered = [version for version in versions if version in per_version]
    hooks = {hook for mapping in per_version.values() for hook in mapping}

    reconciled: dict[str, HookImplementers] = {}
    for hook in sorted(hooks):
        runs: list[tuple[list[str], tuple[str, ...]]] = []
        for version in ordered:
            plugins = per_version[version].get(hook, ())
            if runs and runs[-1][1] == plugins:
                runs[-1][0].append(version)
            else:
                runs.append(([version], plugins))
        reconciled[hook] = HookImplementers(
            hook=hook,
            runs=tuple(Run(tuple(vs), plugins) for vs, plugins in runs),
        )
    return reconciled
