"""Structural capture of pytest's hook call tree.

Loaded as a plugin (``-p pytest_hook_atlas.tracer``), this installs pluggy's
:meth:`~pluggy.PluginManager.add_hookcall_monitoring` and records every hook
call as it happens: the exact nesting, the order, and *which plugin supplied
each implementation*.

This module is deliberately **standalone**: no imports from the rest of the
package, no syntax newer than Python 3.8, and nothing beyond pytest and pluggy.
Capturing old pytest means running it on an old Python (pytest 6.0 caps out at
3.9), where the rest of this package - which needs 3.11 and ``tomllib`` - cannot
be installed. So capture copies this one file next to the test project and
loads it with ``-p hook_atlas_tracer``.

This replaces the previous approach of scraping ``pytest --debug`` output.
Parsing a human-readable log could never see plugin provenance, and broke
whenever pytest changed its log formatting.
"""

from __future__ import annotations

import atexit
import inspect
import json
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pluggy
import pytest

#: Bumped whenever the on-disk trace format changes incompatibly.
SCHEMA_VERSION = 1

#: Hooks whose *original* invocation happens before monitoring can be installed.
#:
#: ``pytest_addoption`` is the earliest hook handed the plugin manager, so it -
#: and the ``pytest_addhooks`` and ``pytest_cmdline_parse`` calls surrounding
#: it - are structurally uncapturable.
#:
#: Note the subtlety: ``pytest_addhooks`` and ``pytest_addoption`` are *historic*
#: hooks, so they replay for plugins registered later. If a conftest or plugin
#: that implements them is loaded after monitoring installs, they will appear in
#: the trace - as a replay, not as the original call. A trace therefore says
#: nothing about whether these ran before it started; they always did.
#:
#: Measured, not assumed: ``tests/test_tracer.py`` fails if this set changes.
PROLOGUE_HOOKS = frozenset({"pytest_cmdline_parse", "pytest_addhooks", "pytest_addoption"})

ENV_TRACE_PATH = "HOOK_ATLAS_TRACE"
ENV_SCENARIO = "HOOK_ATLAS_SCENARIO"
DEFAULT_TRACE_PATH = "hook-atlas-trace.json"


@dataclass
class CallNode:
    """A single hook call, with the calls it made in turn."""

    name: str
    seq: int
    depth: int
    impls: list[dict[str, Any]]
    children: list[CallNode] = field(default_factory=list)
    raised: bool = False

    def to_dict(self) -> dict[str, Any]:
        node: dict[str, Any] = {
            "name": self.name,
            "seq": self.seq,
            "depth": self.depth,
            "impls": self.impls,
        }
        if self.raised:
            node["raised"] = True
        if self.children:
            node["children"] = [child.to_dict() for child in self.children]
        return node


def _raised(outcome: Any) -> bool:
    """Did the hook call raise?

    pluggy >= 1.3 exposes ``Result.exception``; 0.13 and 1.0 expose
    ``_Result.excinfo``. Both are supported so traces can be captured all the
    way back to pytest 6.0.
    """
    if getattr(outcome, "exception", None) is not None:
        return True
    return getattr(outcome, "excinfo", None) is not None


def _impl_info(impl: Any) -> dict[str, Any]:
    """Summarise a pluggy ``HookImpl``.

    ``plugin_name`` is the provenance we care about: for a conftest it is the
    file path, which is what lets a scenario diagram show *where* a hook
    implementation came from.
    """
    function = getattr(impl, "function", None)
    return {
        "plugin": getattr(impl, "plugin_name", None),
        "module": getattr(function, "__module__", None),
        "function": getattr(function, "__qualname__", None),
        "wrapper": bool(getattr(impl, "wrapper", False)),
        "hookwrapper": bool(getattr(impl, "hookwrapper", False)),
        "tryfirst": bool(getattr(impl, "tryfirst", False)),
        "trylast": bool(getattr(impl, "trylast", False)),
    }


def _spec_opts(hookspec_function: Any) -> dict[str, Any]:
    """Read pluggy's hookspec options off a hookspec function.

    pluggy stores these as ``<project_name>_spec``; pytest's project name is
    ``pytest``, but fall back to scanning so this survives a rename upstream.
    """
    opts = getattr(hookspec_function, "pytest_spec", None)
    if isinstance(opts, dict):
        return opts
    for attribute in dir(hookspec_function):
        if attribute.endswith("_spec"):
            candidate = getattr(hookspec_function, attribute)
            if isinstance(candidate, dict):
                return candidate
    return {}


def hookspec_metadata() -> dict[str, dict[str, Any]]:
    """Static facts about every declared pytest hook.

    These are the semantics that prose documents badly and a diagram can show
    at a glance: ``historic`` hooks replay for plugins registered later, and
    ``firstresult`` hooks stop at the first non-``None`` return.
    """
    import _pytest.hookspec as hookspec_module

    metadata: dict[str, dict[str, Any]] = {}
    for name in sorted(dir(hookspec_module)):
        if not name.startswith("pytest_"):
            continue
        function = getattr(hookspec_module, name)
        if not callable(function):
            continue
        opts = _spec_opts(function)
        doc = inspect.getdoc(function) or ""
        metadata[name] = {
            "historic": bool(opts.get("historic")),
            "firstresult": bool(opts.get("firstresult")),
            "argnames": list(inspect.signature(function).parameters),
            "summary": doc.split("\n\n")[0].replace("\n", " ").strip(),
        }
    return metadata


class HookRecorder:
    """Builds a call tree from pluggy's before/after monitoring callbacks."""

    def __init__(self) -> None:
        self.roots: list[CallNode] = []
        self.desyncs: list[str] = []
        self._stack: list[CallNode] = []
        self._seq = 0

    def before(self, hook_name: str, hook_impls: Any, kwargs: Any) -> None:
        self._seq += 1
        node = CallNode(
            name=hook_name,
            seq=self._seq,
            depth=len(self._stack),
            impls=[_impl_info(impl) for impl in hook_impls],
        )
        if self._stack:
            self._stack[-1].children.append(node)
        else:
            self.roots.append(node)
        self._stack.append(node)

    def after(self, outcome: Any, hook_name: str, hook_impls: Any, kwargs: Any) -> None:
        if not self._stack:
            self.desyncs.append(f"after({hook_name}) with empty stack")
            return
        node = self._stack.pop()
        if node.name != hook_name:
            self.desyncs.append(f"expected after({node.name}), got after({hook_name})")
        if _raised(outcome):
            node.raised = True

    def total_calls(self) -> int:
        return self._seq

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "environment": {
                "pytest": pytest.__version__,
                "pluggy": pluggy.__version__,
                "python": platform.python_version(),
                "platform": sys.platform,
            },
            "scenario": {
                "id": os.environ.get(ENV_SCENARIO),
                "argv": sys.argv[1:],
                "invocation_dir": os.getcwd(),
            },
            "stats": {
                "total_calls": self._seq,
                "unique_hooks": len({n for n in _walk_names(self.roots)}),
            },
            "desyncs": self.desyncs,
            "hookspecs": hookspec_metadata(),
            "calls": [root.to_dict() for root in self.roots],
        }


def _walk_names(nodes: list[CallNode]):
    for node in nodes:
        yield node.name
        yield from _walk_names(node.children)


_recorder: HookRecorder | None = None


def trace_path() -> Path:
    return Path(os.environ.get(ENV_TRACE_PATH, DEFAULT_TRACE_PATH))


def write_trace() -> Path | None:
    """Serialise the recorded tree. Returns the path written, if any."""
    if _recorder is None:
        return None
    destination = trace_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(_recorder.to_dict(), indent=2) + "\n")
    return destination


def pytest_addoption(parser, pluginmanager) -> None:
    """Install monitoring as early as pytest will hand us the plugin manager.

    ``pytest_addoption`` is the earliest hook that receives the plugin manager,
    so a handful of hooks fire before this point and cannot be captured; they
    are documented as the trace prologue rather than silently missing.
    """
    global _recorder
    if _recorder is not None:
        return
    _recorder = HookRecorder()
    pluginmanager.add_hookcall_monitoring(_recorder.before, _recorder.after)
    atexit.register(write_trace)
