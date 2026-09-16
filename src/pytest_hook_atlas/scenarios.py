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

from hook_atlas import tracer

from . import hookspec_generator

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

    #: Hooks this scenario exists to reach. Checked by the test suite, so a
    #: scenario that silently stops doing its job fails loudly.
    expects: tuple[str, ...] = ()

    #: Does the session run to completion? Some scenarios end early on purpose -
    #: a KeyboardInterrupt, an exception escaping a hook - and their traces are
    #: legitimately short and missing whole phases.
    complete_run: bool = True

    #: Packages to install alongside pytest in the capture virtualenv. A
    #: scenario exercising a plugin needs the plugin present.
    requires: tuple[str, ...] = ()

    #: Does this scenario run across more than one process? Under xdist the
    #: controller and each worker see different things, so each writes its own
    #: trace and the pages show them separately.
    distributed: bool = False

    #: Fewest hooks a healthy capture of this scenario should see. Zero means no
    #: expectation: nothing in the tooling requires a minimum, because a run
    #: that dies in its first hookimpl should still be drawn as it happened.
    #: This is a statement about what *we* host, not a rule the tool enforces.
    min_hooks: int = 0

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
        expects=tuple(data.get("expects", [])),
        requires=tuple(data.get("requires", [])),
        distributed=data.get("distributed", False),
        complete_run=data.get("complete_run", True),
        min_hooks=data.get("min_hooks", 0),
        path=directory,
    )


def discover(root: Path) -> list[Scenario]:
    scenarios = [
        load_scenario(directory)
        for directory in sorted(root.iterdir())
        if (directory / SCENARIO_FILE).exists()
    ]
    for scenario in scenarios:
        # trace files are named <scenario>.json, or <scenario>.<process>.json
        # for a distributed one, so a dot in an id would make the two ambiguous
        if "." in scenario.id:
            raise ValueError(f"scenario id {scenario.id!r} must not contain a dot")
    return sorted(scenarios, key=lambda scenario: (scenario.order, scenario.id))


#: Name the standalone tracer takes once copied beside a test project.
TRACER_MODULE = "hook_atlas_tracer"
PLUGIN_MODULE = "hook_atlas_pytest"

#: Attaches at pytest_addoption, the earliest hook that is handed the plugin
#: manager. Hooks called before it - pytest_cmdline_parse among them - are not
#: recorded. hook_atlas.tracer.watch() would catch those by wrapping the
#: PluginManager constructor; switching to it changes every trace, so it waits
#: for the re-capture that is planned with the next schema bump.
#: Hooks pytest calls before a plugin can be handed the plugin manager, so
#: capture cannot see them. A consequence of attaching at pytest_addoption, not
#: of pytest: hook_atlas.tracer.watch() wraps the PluginManager constructor and
#: records all three. They are documented as the trace prologue rather than
#: silently missing, and this set shrinks to nothing when capture moves.
PROLOGUE_HOOKS = frozenset({"pytest_cmdline_parse", "pytest_addhooks", "pytest_addoption"})

TRACER_PLUGIN = """\
import hook_atlas_tracer


def pytest_addoption(parser, pluginmanager):
    hook_atlas_tracer.attach(pluginmanager)
"""


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
) -> list[Path]:
    """Run one scenario under the tracer. Returns every trace file written.

    A distributed scenario writes several - one per process - named after
    ``destination`` with the process appended.

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

    # The tracer is copied in rather than imported: the capture interpreter has
    # neither this package nor hook-atlas installed, and on the Pythons old
    # pytest needs it could not have them. The shim beside it is the pytest
    # plugin - the tracer itself knows nothing about pytest.
    shutil.copyfile(Path(tracer.__file__), project / f"{TRACER_MODULE}.py")
    (project / f"{PLUGIN_MODULE}.py").write_text(TRACER_PLUGIN)

    if scenario.generated_conftest:
        _write_generated_conftest(project, interpreter)

    destination.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "HOOK_ATLAS_TRACE": str(destination),
        "HOOK_ATLAS_SCENARIO": scenario.id,
    }
    if scenario.distributed:
        # workers name themselves from PYTEST_XDIST_WORKER; this names the
        # process we launched, so its trace does not collide with theirs
        environment[tracer.ENV_PROCESS] = "controller"

    subprocess.run(
        [
            interpreter,
            "-m",
            "pytest",
            "-p",
            PLUGIN_MODULE,
            str(project),
            *scenario.args,
            "-p",
            "no:cacheprovider",
        ],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,  # scenarios deliberately contain failing tests
    )
    written = sorted(destination.parent.glob(f"{destination.stem}*{destination.suffix}"))
    if not written:
        raise RuntimeError(f"scenario {scenario.id!r} produced no trace")
    return written
