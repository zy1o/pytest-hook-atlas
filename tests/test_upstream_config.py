"""Our phases, against the example config hook-atlas ships.

The config format is defined upstream, and hook-atlas ships pytest's as its
worked example - it is the biggest pluggy application anyone is likely to
describe, so it is what the format gets judged on. Two copies of the same
description will drift, and the drift would be silent: the site would keep
building, from phases that no longer match the example everyone else reads.

So this asserts they agree. When they do not, one of them is wrong, and which
one is a decision rather than something to paper over.
"""

from __future__ import annotations

import pytest

from pytest_hook_atlas import analysis, build, doclinks

config = pytest.importorskip("hook_atlas.config")


@pytest.fixture(scope="module")
def upstream():
    return config.load(config.example("pytest"))


def test_the_phases_match(upstream):
    ours = [(phase.key, phase.title, phase.anchors) for phase in analysis.PHASES]
    theirs = [(phase.key, phase.title, phase.anchors) for phase in upstream.phases]

    assert ours == theirs


def test_the_run_test_fallback_matches(upstream):
    """The one that stops a distributed run's controller being drawn empty."""
    ours = next(phase for phase in analysis.PHASES if phase.key == "runtest")
    theirs = next(phase for phase in upstream.phases if phase.key == "runtest")

    assert ours.fallback_anchors == theirs.fallback_anchors


def test_the_documented_namespaces_match(upstream):
    assert upstream.links.namespaces == frozenset(doclinks.DOCUMENTED_NAMESPACES)
    assert upstream.links.anchor_prefix == doclinks.ANCHOR_PREFIX


def test_the_bookkeeping_hooks_match(upstream):
    """Which hooks stay out of the fingerprint decides how releases group, so a
    difference here would silently repartition the whole site."""
    assert upstream.bookkeeping == build.BOOKKEEPING_HOOKS


def test_the_internal_prefixes_match(upstream):
    assert tuple(upstream.internal) == tuple(build.INTERNAL_PREFIXES)


def test_the_descriptions_match(upstream):
    """Prose too - it is what the page actually says under each heading."""
    ours = {phase.key: " ".join(phase.description.split()) for phase in analysis.PHASES}
    theirs = {phase.key: " ".join(phase.description.split()) for phase in upstream.phases}

    assert ours == theirs
