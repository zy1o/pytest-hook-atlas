"""Build links from hook names into the pytest reference documentation.

This module exists because these links are what broke last time. Two failure
modes, both real:

* pytest moved ``reference.html`` to ``reference/reference.html``.
* Version-pinned docs are not always built. At time of writing ``9.1.x``
  redirects in a loop, while ``8.0.x``, ``8.1.x`` and ``9.0.x`` are fine.

So a pinned URL is *verified* before use, with a documented fallback, and
``linkcheck`` re-verifies everything the site emits.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request

from hook_atlas.doclinks import DocLinks

DOCS_ROOT = "https://docs.pytest.org/en"
FALLBACK_SLUG = "stable"
ANCHOR_PREFIX = "pytest.hookspec"

#: readthedocs returns 403 to urllib's default User-Agent.
USER_AGENT = "pytest-hook-atlas (+https://github.com/zy1o/pytest-hook-atlas)"

_base_cache: dict[str, str] = {}


def version_slug(pytest_version: str) -> str:
    """``"9.1.1"`` -> ``"9.1.x"``, the form readthedocs publishes."""
    parts = pytest_version.split(".")
    if len(parts) < 2:
        return FALLBACK_SLUG
    return f"{parts[0]}.{parts[1]}.x"


def reference_url(slug: str) -> str:
    return f"{DOCS_ROOT}/{slug}/reference/reference.html"


#: Hookspec modules whose documentation we know how to link to. Anything else
#: - a project's own hooks, a plugin we have no URL for - renders unlinked
#: rather than pointing at pytest's reference, where the anchor does not exist.
#: Adding an entry here is how a new source of hooks gains links.
DOCUMENTED_NAMESPACES = {"_pytest.hookspec"}


def links_for(base_url: str, verify: bool = False) -> DocLinks:
    """Where pytest's hook documentation lives, for a resolved base URL.

    Hooks pytest did not declare - xdist contributes twelve, and any project can
    add its own - have no entry in pytest's reference, so ``DOCUMENTED_NAMESPACES``
    keeps them unlinked rather than pointing at an anchor that does not exist.

    With ``verify``, the page is read and only the hooks it actually documents
    are linked. That matters where a release's own documentation is gone -
    pytest 6.0 and 6.1 are not published at all, so those pages fall back to
    `stable`, and a hook pytest has since removed is in the right namespace but
    absent from the page it would point at.
    """
    return DocLinks(
        base_url=base_url,
        anchor_prefix=ANCHOR_PREFIX,
        namespaces=frozenset(DOCUMENTED_NAMESPACES),
        documented=documented_at(base_url) if verify else None,
    )


def hook_url(hook_name: str, base_url: str, declared_in: str | None = None) -> str | None:
    """Documentation URL for a hook, or ``None`` if we have none."""
    return links_for(base_url).url_for(hook_name, declared_in)


def _is_reachable(url: str, timeout: float) -> bool:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        # includes the redirect loop that 9.1.x currently serves
        return False


def resolve_base_url(pytest_version: str, verify: bool = True, timeout: float = 10.0) -> str:
    """Pinned reference URL for this pytest version, falling back to ``stable``.

    With ``verify=False`` the pinned URL is returned unchecked, which keeps
    builds deterministic and offline-friendly.
    """
    slug = version_slug(pytest_version)
    if not verify:
        # Fall back rather than emitting an unverified pin. Some pinned docs do
        # not exist - 9.1.x currently serves a redirect loop - so an offline
        # build that guessed would produce dead links, which is precisely the
        # failure this module exists to prevent.
        return reference_url(FALLBACK_SLUG)

    if slug in _base_cache:
        return _base_cache[slug]

    pinned = reference_url(slug)
    resolved = pinned if _is_reachable(pinned, timeout) else reference_url(FALLBACK_SLUG)
    _base_cache[slug] = resolved
    return resolved


def fetch(url: str, timeout: float = 30.0) -> str:
    """Download a reference page so many anchors can be checked in one request."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def anchor_exists(page: str, hook_name: str) -> bool:
    return f'id="{ANCHOR_PREFIX}.{hook_name}"' in page


_ANCHOR = re.compile(rf'id="{re.escape(ANCHOR_PREFIX)}\.([a-zA-Z_][a-zA-Z0-9_]*)"')


def documented_hooks(page: str) -> frozenset[str]:
    """Every hook the reference page has an anchor for."""
    return frozenset(_ANCHOR.findall(page))


_documented_cache: dict[str, frozenset[str] | None] = {}


_page_cache: dict[str, str] = {}


def fetch_cached(url: str, timeout: float = 30.0) -> str:
    """``fetch``, remembering each page for the life of the process.

    The site resolves a handful of reference URLs and asks each the same
    question for every trace. Fetching once per trace meant hundreds of
    downloads of the same page, which is slow and is how a transient connection
    reset came to fail a whole run.
    """
    if url not in _page_cache:
        _page_cache[url] = fetch(url, timeout)
    return _page_cache[url]


def documented_at(base_url: str, timeout: float = 30.0) -> frozenset[str] | None:
    """Which hooks that reference page documents, or ``None`` if unreachable.

    Cached per URL: the site resolves a handful of base URLs and asks each the
    same question for every hook on every page.
    """
    if base_url not in _documented_cache:
        try:
            _documented_cache[base_url] = documented_hooks(fetch_cached(base_url, timeout))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
            # Unreachable is not the same as "documents nothing". Withholding
            # every link because a fetch failed would be a worse answer than
            # linking optimistically, which is what None asks for.
            _documented_cache[base_url] = None
    return _documented_cache[base_url]
