"""Capturing releases that need an interpreter this package cannot run on.

pytest 6.0 tops out at Python 3.9; this package needs 3.11. So the capture
virtualenv has to be built from a different interpreter than the one running,
and the combination of an old pytest with a modern plugin has to be refused
rather than silently resolved into something else.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pytest_hook_atlas import matrix, scenarios


def scenario(tmp_path, **fields):
    directory = tmp_path / fields.get("id", "demo")
    directory.mkdir(exist_ok=True)
    (directory / "test_x.py").write_text("def test_x():\n    assert True\n")
    body = "\n".join(f"{key} = {value!r}" for key, value in fields.items() if key != "id")
    (directory / "scenario.toml").write_text(
        f'id = "{fields.get("id", "demo")}"\ntitle = "Demo"\nsummary = "s"\n'
        f'description = "d"\norder = 1\n{body}\n'
    )
    return scenarios.load_scenario(directory)


def test_a_scenario_without_a_floor_applies_everywhere(tmp_path):
    assert scenario(tmp_path).applies_to("6.0.0")


def test_a_scenario_declares_which_releases_it_supports(tmp_path):
    limited = scenario(tmp_path, pytest_versions=">=7.0")

    assert not limited.applies_to("6.0.0")
    assert limited.applies_to("7.3.2")


def test_the_xdist_scenario_declares_its_floor():
    """pytest-xdist 3.8 needs pytest 7. Without the declaration, pip installs a
    newer pytest to satisfy it and the capture is filed under the wrong one."""
    xdist = next(s for s in scenarios.discover(Path("scenarios")) if s.id == "xdist")

    assert xdist.pytest_versions
    assert not xdist.applies_to("6.0.0")


def test_a_release_is_complete_without_scenarios_that_cannot_run(tmp_path):
    """Otherwise pytest 6.0 is missing xdist forever and gets re-attempted
    on every watcher run."""
    traces = tmp_path / "traces"
    (traces / "6.0.0").mkdir(parents=True)
    (traces / "6.0.0" / "demo.json").write_text("{}")
    declared = [
        scenario(tmp_path, id="demo"),
        scenario(tmp_path, id="modern", pytest_versions=">=7.0"),
    ]

    assert matrix.captured_versions(traces, declared) == {"6.0.0"}


def test_the_wrong_pytest_is_refused(tmp_path, monkeypatch):
    """The failure this exists to prevent is silent: pip upgrades pytest to
    satisfy a plugin, and the trace describes a release it is not filed under."""

    def pretend(command, **kwargs):
        if command[1:3] == ["-c", "import pytest; print(pytest.__version__)"]:
            return subprocess.CompletedProcess(command, 0, stdout="8.4.2\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(matrix.subprocess, "run", pretend)

    with pytest.raises(matrix.WrongPytest, match="asked for pytest 6.0.0.*holds 8.4.2"):
        matrix.provision("6.0.0", tmp_path, ("pytest-xdist==3.8.0",))


def test_the_right_pytest_passes(tmp_path, monkeypatch):
    def pretend(command, **kwargs):
        if command[1:3] == ["-c", "import pytest; print(pytest.__version__)"]:
            return subprocess.CompletedProcess(command, 0, stdout="6.0.0\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(matrix.subprocess, "run", pretend)

    assert matrix.provision("6.0.0", tmp_path, ()).name == "python"


def test_provision_builds_from_the_interpreter_it_is_given(tmp_path, monkeypatch):
    """Old pytest needs an old python, which cannot be the one running this."""
    seen = []

    def pretend(command, **kwargs):
        seen.append(command)
        if command[1:3] == ["-c", "import pytest; print(pytest.__version__)"]:
            return subprocess.CompletedProcess(command, 0, stdout="6.0.0\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(matrix.subprocess, "run", pretend)
    matrix.provision("6.0.0", tmp_path, (), base_python="/usr/bin/python3.9")

    assert seen[0][:3] == ["/usr/bin/python3.9", "-m", "venv"]


# --------------------------------------------------------------------------
# rendering fewer majors than are kept


def test_retention_governs_rendering_not_storage(tmp_path):
    """Every trace stays committed. Widening the window and rebuilding brings
    older releases back with no re-capture, which is the point of keeping them."""
    from hook_atlas.grouping import Group

    from pytest_hook_atlas import build

    groups = [
        Group("a", ("6.0.0",), "pytest"),
        Group("b", ("7.0.0",), "pytest"),
        Group("c", ("8.0.0",), "pytest"),
        Group("d", ("9.0.0",), "pytest"),
    ]
    item = build.ScenarioBuild(scenario=None, traces={}, groups=groups, majors=2)

    assert [g.versions[0] for g in item.rendered] == ["8.0.0", "9.0.0"]
    assert len(item.groups) == 4, "storage is untouched"


def test_zero_majors_renders_everything(tmp_path):
    from hook_atlas.grouping import Group

    from pytest_hook_atlas import build

    groups = [Group("a", ("6.0.0",), "pytest"), Group("b", ("9.0.0",), "pytest")]
    item = build.ScenarioBuild(scenario=None, traces={}, groups=groups, majors=0)

    assert len(item.rendered) == 2
