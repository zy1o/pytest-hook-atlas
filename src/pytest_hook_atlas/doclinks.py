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

import urllib.error
import urllib.request

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


def hook_url(hook_name: str, base_url: str) -> str:
    return f"{base_url}#{ANCHOR_PREFIX}.{hook_name}"


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
