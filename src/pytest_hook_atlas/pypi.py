"""Ask PyPI what pytest releases exist, and which we can capture.

The watcher needs three facts about each release that only PyPI knows: when it
appeared, whether it has been yanked, and which Pythons it runs on. That last
one is a hard constraint rather than a preference - pytest 6.0 tops out at
Python 3.9 and pytest 9.0 requires 3.10, so no single interpreter can capture
the whole range.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

PYPI_JSON = "https://pypi.org/pypi/{package}/json"
USER_AGENT = "pytest-hook-atlas (+https://github.com/zy1o/pytest-hook-atlas)"

#: pytest 6.0 is where this project starts; older releases predate the
#: hookspec layout the diagrams are built around.
FLOOR = Version("6.0")


@dataclass(frozen=True)
class Release:
    """One published release of a package."""

    version: str
    parsed: Version
    uploaded: datetime
    yanked: bool
    requires_python: str | None
    pythons: tuple[str, ...]

    def runs_on(self, python: str) -> bool:
        """Can ``python`` (``"3.12"``) run this release?

        Trove classifiers give the upper bound, which ``requires_python`` never
        does - pytest 6.0 declares ``>=3.5`` but only claims support to 3.9.
        Both are consulted; classifiers win when present.
        """
        if self.requires_python:
            try:
                if python not in SpecifierSet(self.requires_python):
                    return False
            except InvalidSpecifier:
                pass
        if self.pythons:
            return python in self.pythons
        # classifiers were not fetched; requires_python is the only bound
        return True


def _fetch(package: str, timeout: float) -> dict:
    request = urllib.request.Request(
        PYPI_JSON.format(package=package), headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _classifier_pythons(classifiers: list[str]) -> tuple[str, ...]:
    prefix = "Programming Language :: Python :: "
    found = []
    for classifier in classifiers or ():
        if classifier.startswith(prefix):
            value = classifier[len(prefix) :].strip()
            if value.count(".") == 1:  # "3.12", not "3" or "3 :: Only"
                found.append(value)
    return tuple(sorted(found, key=lambda v: Version(v)))


def releases(
    package: str = "pytest",
    floor: Version = FLOOR,
    include_prereleases: bool = False,
    detailed: bool = False,
    timeout: float = 30.0,
) -> list[Release]:
    """Every published release at or above ``floor``, oldest first.

    ``detailed`` fetches each release's Trove classifiers with its own request.
    That is the only way to learn a release's *upper* Python bound, but it costs
    one request per release, so it is off by default: the weekly watcher only
    ever looks at brand-new releases, which run on current Pythons anyway. The
    one-off backfill wants it on.
    """
    data = _fetch(package, timeout)
    found: list[Release] = []

    for version, files in data["releases"].items():
        if not files:
            continue
        try:
            parsed = Version(version)
        except InvalidVersion:
            continue
        if parsed < floor:
            continue
        if parsed.is_prerelease and not include_prereleases:
            continue

        uploaded = min(entry["upload_time_iso_8601"] for entry in files)
        found.append(
            Release(
                version=version,
                parsed=parsed,
                uploaded=datetime.fromisoformat(uploaded.replace("Z", "+00:00")),
                # a release counts as yanked only if every file is
                yanked=all(entry.get("yanked") for entry in files),
                requires_python=next(
                    (e.get("requires_python") for e in files if e.get("requires_python")), None
                ),
                pythons=release_classifiers(package, version, timeout) if detailed else (),
            )
        )

    found.sort(key=lambda release: release.parsed)
    return found


def release_classifiers(package: str, version: str, timeout: float = 30.0) -> tuple[str, ...]:
    """Python versions a specific release claims to support."""
    data = _fetch(f"{package}/{version}", timeout)
    return _classifier_pythons(data["info"].get("classifiers", []))
