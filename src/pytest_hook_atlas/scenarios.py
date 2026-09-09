"""Discover and run capture scenarios.

A scenario is a directory holding a small pytest project plus a
``scenario.toml`` describing how to invoke it. The flow chart genuinely differs
between them - that difference is the point of the site - so every rendered
page links back to the directory that produced it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import hookspec_generator, tracer

REPO_URL = "https://github.com/zy1o/pytest-hook-atlas"
SCENARIO_FILE = "scenario.toml"


@dataclass(frozen=True)
class Scenario:
    """A capture scenario, loaded from ``scenario.toml``."""

    id: str
    title: str
    summary: str
    description: str
    args: tuple[str, ...]
    path: Path
    order: int = 99
    generated_conftest: bool = False

    @property
    def source_url(self) -> str:
        """Where a reader can go to read the code behind a diagram."""
        return f"{REPO_URL}/tree/main/scenarios/{self.id}"

    def source_files(self) -> list[Path]:
        """Project files, excluding the scenario metadata itself."""
        return sorted(
            path for path in self.path.iterdir() if path.is_file() and path.name != SCENARIO_FILE
        )


def load_scenario(directory: Path) -> Scenario:
    data = tomllib.loads((directory / SCENARIO_FILE).read_text())
    return Scenario(
        id=data["id"],
        title=data["title"],
        summary=data.get("summary", ""),
        description=data.get("description", "").strip(),
        args=tuple(data.get("args", [])),
        order=data.get("order", 99),
        generated_conftest=data.get("generated_conftest", False),
        path=directory,
    )


def discover(root: Path) -> list[Scenario]:
    scenarios = [
        load_scenario(directory)
        for directory in sorted(root.iterdir())
        if (directory / SCENARIO_FILE).exists()
    ]
    return sorted(scenarios, key=lambda scenario: (scenario.order, scenario.id))


#: Name the standalone tracer takes once copied beside a test project.
TRACER_MODULE = "hook_atlas_tracer"


def _write_generated_conftest(project: Path, interpreter: str) -> None:
    """Generate the all-hooks conftest using the *target* pytest.

    The declared hook set differs between pytest versions, so this has to run
    in the environment being captured rather than in ours.
    """
    generator = project / "_hookspec_generator.py"
    shutil.copyfile(Path(hookspec_generator.__file__), generator)
    result = subprocess.run(
        [interpreter, str(generator)],
        capture_output=True,
        text=True,
        check=True,
    )
    (project / "conftest.py").write_text(result.stdout)
    generator.unlink()


def capture(
    scenario: Scenario,
    destination: Path,
    workdir: Path,
    python: str | None = None,
) -> Path:
    """Run one scenario under the tracer, writing its trace to ``destination``.

    The project is copied to a scratch directory first so that generated files
    and ``__pycache__`` never land in the committed scenario source.

    ``python`` selects the interpreter, which for the version matrix is a venv
    holding some older pytest. The tracer is copied in as a single file rather
    than imported from this package, because that interpreter will not have
    this package installed - and on Python 3.9 could not.
    """
    # the subprocess runs with cwd inside the copied project, so a relative
    # destination would land there rather than in the repo
    destination = destination.resolve()
    interpreter = python or sys.executable
    project = workdir / scenario.id
    if project.exists():
        shutil.rmtree(project)
    shutil.copytree(scenario.path, project)

    shutil.copyfile(Path(tracer.__file__), project / f"{TRACER_MODULE}.py")

    if scenario.generated_conftest:
        _write_generated_conftest(project, interpreter)

    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            interpreter,
            "-m",
            "pytest",
            "-p",
            TRACER_MODULE,
            str(project),
            *scenario.args,
            "-p",
            "no:cacheprovider",
        ],
        cwd=project,
        env={
            **os.environ,
            "HOOK_ATLAS_TRACE": str(destination),
            "HOOK_ATLAS_SCENARIO": scenario.id,
        },
        capture_output=True,
        text=True,
        check=False,  # scenarios deliberately contain failing tests
    )
    if not destination.exists():
        raise RuntimeError(f"scenario {scenario.id!r} produced no trace")
    return destination
