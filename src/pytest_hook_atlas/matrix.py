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
import venv
from dataclasses import dataclass
from pathlib import Path

from .pypi import Release
from .scenarios import Scenario, capture

CURRENT_PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"


@dataclass
class CaptureResult:
    """What happened when we tried to capture one pytest release."""

    version: str
    traces: list[Path]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def captured_pairs(traces_dir: Path) -> set[tuple[str, str]]:
    """``(pytest version, scenario id)`` pairs already recorded on disk."""
    if not traces_dir.exists():
        return set()
    return {
        (version.name, trace.stem)
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

    wanted = {scenario.id for scenario in scenarios}
    by_version: dict[str, set[str]] = {}
    for version, scenario_id in pairs:
        by_version.setdefault(version, set()).add(scenario_id)
    return {version for version, found in by_version.items() if wanted <= found}


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


def provision(pytest_version: str, workdir: Path) -> Path:
    """Build a virtualenv holding exactly ``pytest_version``. Returns its python."""
    environment = workdir / f"venv-{pytest_version}"
    venv.create(environment, with_pip=True, clear=True)
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
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return python


def capture_release(
    release: Release, scenarios: list[Scenario], traces_dir: Path, workdir: Path
) -> CaptureResult:
    """Capture every scenario against one pytest release."""
    try:
        python = provision(release.version, workdir)
    except subprocess.CalledProcessError as error:
        return CaptureResult(release.version, [], f"install failed: {error.stderr.strip()[:400]}")

    destination = traces_dir / release.version
    written = []
    for scenario in scenarios:
        try:
            written.append(
                capture(
                    scenario,
                    destination / f"{scenario.id}.json",
                    workdir,
                    python=str(python),
                )
            )
        except Exception as error:  # noqa: BLE001 - one bad scenario must not stop the run
            return CaptureResult(release.version, written, f"{scenario.id}: {error}")
    return CaptureResult(release.version, written)
