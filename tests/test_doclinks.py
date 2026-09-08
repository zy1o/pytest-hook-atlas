"""Tests for pytest documentation link construction.

These links are what broke last time, so the rules are pinned here.
"""

from __future__ import annotations

import pytest

from pytest_hook_atlas import doclinks


@pytest.mark.parametrize(
    ("version", "expected"),
    [("9.1.1", "9.1.x"), ("8.0.2", "8.0.x"), ("10.0.0rc1", "10.0.x"), ("9", "stable")],
)
def test_version_slug(version, expected):
    assert doclinks.version_slug(version) == expected


def test_reference_url_uses_the_current_nested_path():
    """pytest moved reference.html under reference/; the old path 302s."""
    assert doclinks.reference_url("9.0.x").endswith("/9.0.x/reference/reference.html")


def test_hook_url_targets_the_hookspec_anchor():
    url = doclinks.hook_url("pytest_runtest_setup", doclinks.reference_url("stable"))

    assert url.endswith("#pytest.hookspec.pytest_runtest_setup")


def test_unverified_resolution_stays_offline_and_pinned():
    assert doclinks.resolve_base_url("8.1.0", verify=False) == doclinks.reference_url("8.1.x")


def test_resolution_falls_back_when_pinned_docs_are_unavailable(monkeypatch):
    """9.1.x currently serves a redirect loop; the site must not link into it."""
    monkeypatch.setattr(doclinks, "_base_cache", {})
    monkeypatch.setattr(doclinks, "_is_reachable", lambda url, timeout: False)

    assert doclinks.resolve_base_url("9.1.1") == doclinks.reference_url("stable")


def test_resolution_prefers_the_pinned_version_when_it_works(monkeypatch):
    monkeypatch.setattr(doclinks, "_base_cache", {})
    monkeypatch.setattr(doclinks, "_is_reachable", lambda url, timeout: True)

    assert doclinks.resolve_base_url("8.0.2") == doclinks.reference_url("8.0.x")


def test_anchor_exists():
    page = '<dt id="pytest.hookspec.pytest_configure">'

    assert doclinks.anchor_exists(page, "pytest_configure")
    assert not doclinks.anchor_exists(page, "pytest_nonexistent")
