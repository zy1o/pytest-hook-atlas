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


def test_unverified_resolution_falls_back_rather_than_guessing():
    """An offline build must not emit a pin it could not check.

    Some pinned docs do not exist - 9.1.x serves a redirect loop - so guessing
    produces exactly the dead links this module exists to prevent.
    """
    assert doclinks.resolve_base_url("8.1.0", verify=False) == doclinks.reference_url("stable")


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


def test_hooks_pytest_did_not_declare_get_no_link():
    """xdist declares twelve hooks; a project can declare its own. None of them
    have an entry in pytest's reference, so linking there would produce exactly
    the dead anchors this module exists to prevent."""
    base = doclinks.reference_url("stable")

    assert doclinks.hook_url("pytest_runtest_setup", base, "_pytest.hookspec")
    assert doclinks.hook_url("pytest_xdist_make_scheduler", base, "xdist.newhooks") is None
    assert doclinks.hook_url("pytest_company_thing", base, "acme.hooks") is None


def test_an_unknown_origin_still_links():
    """Callers that do not know where a hook came from keep the old behaviour."""
    base = doclinks.reference_url("stable")

    assert doclinks.hook_url("pytest_runtest_setup", base) is not None


# --------------------------------------------------------------------------
# linking only what a page actually documents


SAMPLE_PAGE = """
<dl><dt id="pytest.hookspec.pytest_configure">configure</dt></dl>
<dl><dt id="pytest.hookspec.pytest_runtest_setup">setup</dt></dl>
"""


def test_documented_hooks_reads_the_anchors_a_page_has():
    assert doclinks.documented_hooks(SAMPLE_PAGE) == {
        "pytest_configure",
        "pytest_runtest_setup",
    }


def test_a_hook_the_page_does_not_document_is_not_linked(monkeypatch):
    """pytest 6.0 and 6.1 have no published documentation, so their pages fall
    back to `stable` - where hooks pytest has removed since do not exist. The
    namespace still allows them, which is how the site came to emit links that
    404ed."""
    monkeypatch.setattr(doclinks, "_documented_cache", {})
    monkeypatch.setattr(doclinks, "fetch", lambda url, timeout=30.0: SAMPLE_PAGE)

    links = doclinks.links_for("https://example/ref.html", verify=True)

    assert links.url_for("pytest_configure", "_pytest.hookspec")
    assert links.url_for("pytest_warning_captured", "_pytest.hookspec") is None


def test_without_verification_everything_in_the_namespace_still_links(monkeypatch):
    """Offline builds cannot read the page, and withholding every link would be
    a worse answer than the one the namespace gives."""
    links = doclinks.links_for("https://example/ref.html")

    assert links.url_for("pytest_warning_captured", "_pytest.hookspec")


def test_an_unreachable_page_does_not_withhold_every_link(monkeypatch):
    """A failed fetch is not evidence that a page documents nothing."""
    monkeypatch.setattr(doclinks, "_documented_cache", {})

    def unreachable(url, timeout=30.0):
        raise OSError("connection reset by peer")

    monkeypatch.setattr(doclinks, "fetch", unreachable)

    links = doclinks.links_for("https://example/ref.html", verify=True)

    assert links.url_for("pytest_configure", "_pytest.hookspec")


def test_a_reference_page_is_fetched_once_per_url(monkeypatch):
    """linkcheck asks the same handful of pages about hundreds of traces.

    Fetching per trace made a run take minutes and gave a transient connection
    reset hundreds of chances to land - which is how one failed.
    """
    calls = []

    def counting(url, timeout=30.0):
        calls.append(url)
        return SAMPLE_PAGE

    monkeypatch.setattr(doclinks, "_page_cache", {})
    monkeypatch.setattr(doclinks, "fetch", counting)

    for _ in range(5):
        doclinks.fetch_cached("https://example/ref.html")
    doclinks.fetch_cached("https://example/other.html")

    assert calls == ["https://example/ref.html", "https://example/other.html"]
