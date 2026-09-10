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


@dataclass(frozen=True)
class Implementation:
    """One plugin's implementation of one hook."""

    plugin: str
    owner: str

    @property
    def label(self) -> str:
        """Full name, with the plugin's registered name when it differs.

        The two are genuinely different things: ``capturemanager`` is an
        instance of ``CaptureManager`` living in ``_pytest.capture``, and the
        registered name is what you would pass to ``-p`` or look up with
        ``pluginmanager.get_plugin()``. Showing only one loses something.
        """
        if not self.owner:
            return self.plugin
        tail = self.owner.rsplit(".", 1)[-1]
        if self.plugin and self.plugin.lower() != tail.lower():
            return f"{self.owner} ({self.plugin})"
        return self.owner

    @property
    def key(self) -> tuple[str, str]:
        return (self.plugin, self.owner)


@dataclass(frozen=True)
class Run:
    """A stretch of consecutive releases agreeing on who implements a hook."""

    versions: tuple[str, ...]
    implementations: tuple[Implementation, ...]

    @property
    def plugins(self) -> tuple[str, ...]:
        return tuple(item.plugin for item in self.implementations)

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
    def current(self) -> tuple[Implementation, ...]:
        """The newest release's answer, which is what the diagrams reflect."""
        return self.runs[-1].implementations if self.runs else ()

    def deltas(self) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
        """Each change as (release, gained, lost) rather than a full re-listing.

        pytest_configure is implemented by eighteen plugins and changed five
        times across one page's range; printing the whole list five times is
        unreadable. What changed is short, and is what a reader wants.

        Gains and losses are full labels, not bare plugin names: "gained
        ``_pytest.unraisableexception``" says where to look, where "gained
        ``unraisableexception``" only says what it is called.
        """
        changes = []
        for older, newer in zip(self.runs, self.runs[1:], strict=False):
            before = {item.key: item for item in older.implementations}
            after = {item.key: item for item in newer.implementations}
            gained = tuple(sorted(after[k].label for k in after.keys() - before.keys()))
            lost = tuple(sorted(before[k].label for k in before.keys() - after.keys()))
            changes.append((newer.versions[0], gained, lost))
        return changes

    @property
    def changed_at(self) -> str | None:
        """The release the newest answer first applied from, if it changed."""
        if self.stable:
            return None
        return self.runs[-1].versions[0]


def _owner(impl: dict[str, Any], hook: str) -> str:
    """Where the implementation lives: module, or module.Class for a method.

    The qualname ends with the hook name, which is the table row already, so it
    is trimmed: ``_pytest.capture.CaptureManager.pytest_runtest_setup`` reads
    better as ``_pytest.capture.CaptureManager``.
    """
    module = impl.get("module") or ""
    function = impl.get("function") or ""
    qualifier = function[: -len(hook)].rstrip(".") if function.endswith(hook) else function
    return ".".join(part for part in (module, qualifier) if part)


def _implementations_by_hook(trace: dict[str, Any]) -> dict[str, tuple[Implementation, ...]]:
    """Implementations per hook, in the order pluggy called them.

    Order is not incidental - it is tryfirst/trylast and registration order,
    and it decides which implementation wins a firstresult hook. Sorting the
    list alphabetically, as an earlier version did, threw that away.

    pluggy stores hook_impls in *reverse* call order and iterates them with
    ``reversed()``, which is why a ``trylast`` implementation sits at index 0.
    They are reversed here so the table reads top to bottom in the order pytest
    actually runs them.
    """
    found: dict[str, list[Implementation]] = {}
    seen: dict[str, set[tuple[str, str]]] = {}

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            hook = node["name"]
            bucket = found.setdefault(hook, [])
            known = seen.setdefault(hook, set())
            for impl in reversed(node.get("impls", [])):
                item = Implementation(
                    plugin=str(impl.get("plugin") or ""), owner=_owner(impl, hook)
                )
                if item.key not in known:
                    known.add(item.key)
                    bucket.append(item)
            walk(node.get("children", []))

    walk(trace["calls"])
    return {hook: tuple(items) for hook, items in found.items()}


def reconcile(
    traces: dict[str, dict[str, Any]], versions: tuple[str, ...]
) -> dict[str, HookImplementers]:
    """Collapse per-release implementer sets into runs, oldest first.

    ``versions`` must already be in release order - it comes from a group, which
    is built that way.
    """
    per_version = {
        version: _implementations_by_hook(traces[version])
        for version in versions
        if version in traces
    }
    if not per_version:
        return {}

    ordered = [version for version in versions if version in per_version]
    hooks = {hook for mapping in per_version.values() for hook in mapping}

    reconciled: dict[str, HookImplementers] = {}
    for hook in sorted(hooks):
        runs: list[tuple[list[str], tuple[Implementation, ...]]] = []
        for version in ordered:
            items = per_version[version].get(hook, ())
            # compared as a set so a pure ordering difference does not split a
            # run, while the run itself keeps the newest release's call order
            if runs and {i.key for i in runs[-1][1]} == {i.key for i in items}:
                runs[-1][0].append(version)
                runs[-1] = (runs[-1][0], items)
            else:
                runs.append(([version], items))
        reconciled[hook] = HookImplementers(
            hook=hook,
            runs=tuple(Run(tuple(vs), items) for vs, items in runs),
        )
    return reconciled
