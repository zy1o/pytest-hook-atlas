"""Capture scenarios against pytest versions other than the installed one.

Each pytest version gets a throwaway virtualenv holding exactly that release.
The tracer is a standalone file copied in at capture time, so these venvs never
need this package - which matters, because on the Pythons that old pytest
requires it could not be installed anyway.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from hook_atlas.pypi import Release

from .scenarios import Scenario, capture

CURRENT_PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"


@dataclass
class CaptureResult:
    """What happened when we tried to capture one pytest release."""

    version: str
    traces: list[Path]
    error: str | None = None
    #: Scenarios deliberately not captured for this release, and why.
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


def scenario_id_of(trace: Path) -> str:
    """The scenario a trace file belongs to.

    A distributed scenario writes ``<scenario>.<process>.json``, so the id is
    everything before the first dot. Scenario ids therefore may not contain one
    - which ``discover`` checks, rather than leaving it to produce a puzzling
    result here.
    """
    return trace.name.split(".", 1)[0]


def captured_pairs(traces_dir: Path) -> set[tuple[str, str]]:
    """``(pytest version, scenario id)`` pairs already recorded on disk."""
    if not traces_dir.exists():
        return set()
    return {
        (version.name, scenario_id_of(trace))
        for version in traces_dir.iterdir()
        if version.is_dir()
        for trace in version.glob("*.json")
    }


def captured_versions(traces_dir: Path, scenarios: list[Scenario] | None = None) -> set[str]:
    """Versions captured for *every* scenario in ``scenarios``.

    Keyed on (version, scenario) rather than version alone. Treating a version
    directory containing any .json as "captured" meant that adding a scenario
    left all existing versions looking complete, so capture-missing reported
    nothing to do and the new scenario was never backfilled - a silent no-op
    that would have been baffling to diagnose later.
    """
    pairs = captured_pairs(traces_dir)
    if scenarios is None:
        return {version for version, _ in pairs}

    by_version: dict[str, set[str]] = {}
    for version, scenario_id in pairs:
        by_version.setdefault(version, set()).add(scenario_id)

    # A scenario that cannot run against a release is not missing from it. The
    # xdist scenario needs pytest 7, so counting it against pytest 6.0 would
    # leave that release permanently incomplete and re-attempted forever.
    return {
        version
        for version, found in by_version.items()
        if {s.id for s in scenarios if s.applies_to(version)} <= found
    }


def outstanding(
    releases: list[Release],
    traces_dir: Path,
    python: str = CURRENT_PYTHON,
    force: bool = False,
    scenarios: list[Scenario] | None = None,
) -> list[Release]:
    """Releases worth capturing now: not yanked, not captured, runnable here.

    Yanked releases are skipped deliberately. They have been withdrawn, so
    documenting their hook flow would advertise something nobody should install
    - and pip only installs them at all when pinned exactly, which is what the
    matrix does.
    """
    # ``force`` exists to correct traces captured before this was the only
    # capture path. Traces are otherwise immutable: each is a fact about one
    # exact (pytest, pluggy, Python) triple, and re-capturing against different
    # dependencies would make version-to-version comparisons meaningless.
    already = set() if force else captured_versions(traces_dir, scenarios)
    return [
        release
        for release in releases
        if not release.yanked and release.version not in already and release.runs_on(python)
    ]


class WrongPytest(RuntimeError):
    """A virtualenv did not end up holding the pytest that was asked for."""


def provision(
    pytest_version: str,
    workdir: Path,
    requires: tuple[str, ...] = (),
    base_python: str | None = None,
) -> Path:
    """Build a virtualenv holding ``pytest_version`` and whatever a scenario needs.

    ``requires`` is how a scenario brings its own plugin - pytest-xdist, say.
    The environment is otherwise bare, so a scenario's traces show its plugin
    and nothing else that happens to be installed here.

    ``base_python`` is the interpreter to build it from. Old pytest needs an old
    interpreter - 6.0 tops out at Python 3.9 - and the interpreter running this
    package cannot be that old, because the package needs 3.11.
    """
    environment = workdir / f"venv-{pytest_version}-{'-'.join(requires) or 'bare'}"
    subprocess.run(
        [base_python or sys.executable, "-m", "venv", "--clear", str(environment)],
        capture_output=True,
        text=True,
        check=True,
    )
    python = environment / ("Scripts" if platform.system() == "Windows" else "bin") / "python"

    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--disable-pip-version-check",
            f"pytest=={pytest_version}",
            *requires,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    _confirm_pytest(python, pytest_version, requires)
    return python


def _confirm_pytest(python: Path, wanted: str, requires: tuple[str, ...]) -> None:
    """Refuse to capture an environment holding a different pytest than asked.

    pip resolves the whole command at once, so a plugin with a floor on pytest
    silently upgrades it: asking for pytest 6.0.0 alongside pytest-xdist 3.8.0
    installs pytest 8.4.2, and the capture would be filed under 6.0.0 while
    describing 8.4.2. Nothing downstream could tell.
    """
    result = subprocess.run(
        [str(python), "-c", "import pytest; print(pytest.__version__)"],
        capture_output=True,
        text=True,
        check=True,
    )
    installed = result.stdout.strip()
    if installed != wanted:
        raise WrongPytest(
            f"asked for pytest {wanted} but the environment holds {installed}"
            + (f"; {' '.join(requires)} forced it up" if requires else "")
        )


def capture_release(
    release: Release,
    scenarios: list[Scenario],
    traces_dir: Path,
    workdir: Path,
    base_python: str | None = None,
) -> CaptureResult:
    """Capture every scenario against one pytest release.

    One virtualenv per distinct set of requirements, not one shared between
    scenarios. Installing the union would let a plugin one scenario asked for
    show up in every other scenario's trace: the xdist scenario's dependency
    put twelve xdist hookspecs into the baseline scenario's pages, which is
    precisely the environment poisoning this project refuses to do.
    """
    destination = traces_dir / release.version
    written: list[Path] = []
    skipped: list[str] = []

    by_requirements: dict[tuple[str, ...], list[Scenario]] = {}
    for scenario in scenarios:
        if not scenario.applies_to(release.version):
            skipped.append(f"{scenario.id}: needs pytest {scenario.pytest_versions}")
            continue
        by_requirements.setdefault(tuple(sorted(scenario.requires)), []).append(scenario)

    for requires, group in sorted(by_requirements.items()):
        try:
            python = provision(release.version, workdir, requires, base_python)
        except (subprocess.CalledProcessError, WrongPytest) as error:
            # One unsatisfiable set of requirements must not cost the release
            # its other scenarios - under an old pytest that is most of them.
            detail = getattr(error, "stderr", None) or str(error)
            for scenario in group:
                skipped.append(f"{scenario.id}: {str(detail).strip()[:200]}")
            continue
        for scenario in group:
            try:
                written.extend(
                    capture(
                        scenario,
                        destination / f"{scenario.id}.json",
                        workdir,
                        python=str(python),
                    )
                )
            except Exception as error:  # noqa: BLE001 - one bad scenario must not stop the run
                return CaptureResult(release.version, written, f"{scenario.id}: {error}", skipped)
    return CaptureResult(release.version, written, None, skipped)
