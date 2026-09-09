"""Tests for release discovery and the version matrix.

Nothing here touches the network: PyPI's payload shape is pinned as a fixture
so the parsing rules stay tested even offline.
"""

from __future__ import annotations

from datetime import datetime

from packaging.version import Version

from pytest_hook_atlas import matrix, pypi


def make_release(version, yanked=False, requires="", pythons=()):
    return pypi.Release(
        version=version,
        parsed=Version(version),
        uploaded=datetime(2024, 1, 1),
        yanked=yanked,
        requires_python=requires or None,
        pythons=tuple(pythons),
    )


def test_classifiers_give_the_upper_python_bound():
    """requires_python never expresses a ceiling; classifiers do."""
    old = make_release("6.0.0", requires=">=3.5", pythons=("3.5", "3.9"))

    assert old.runs_on("3.9")
    assert not old.runs_on("3.12")


def test_requires_python_gives_the_lower_bound():
    new = make_release("9.0.0", requires=">=3.10", pythons=("3.10", "3.12"))

    assert not new.runs_on("3.9")
    assert new.runs_on("3.12")


def test_without_classifiers_only_the_lower_bound_applies():
    """The bulk PyPI endpoint omits classifiers for older releases."""
    unknown = make_release("8.0.0", requires=">=3.8")

    assert unknown.runs_on("3.12")
    assert not unknown.runs_on("3.7")


def test_malformed_requires_python_does_not_crash():
    broken = make_release("8.0.0", requires="not-a-specifier")

    assert broken.runs_on("3.12")


def test_classifier_parsing_keeps_only_minor_versions():
    parsed = pypi._classifier_pythons(
        [
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3 :: Only",
            "Programming Language :: Python :: 3.9",
            "Programming Language :: Python :: 3.12",
            "Topic :: Software Development :: Testing",
        ]
    )

    assert parsed == ("3.9", "3.12")


def test_yanked_releases_are_never_captured(tmp_path):
    """pytest 8.1.0 is really yanked; documenting it would advertise it."""
    releases = [make_release("8.1.0", yanked=True), make_release("8.1.1")]

    outstanding = matrix.outstanding(releases, tmp_path)

    assert [r.version for r in outstanding] == ["8.1.1"]


def test_already_captured_releases_are_skipped(tmp_path):
    (tmp_path / "8.1.1").mkdir()
    (tmp_path / "8.1.1" / "baseline.json").write_text("{}")

    releases = [make_release("8.1.1"), make_release("8.2.0")]

    assert [r.version for r in matrix.outstanding(releases, tmp_path)] == ["8.2.0"]


def test_captured_versions_ignores_empty_directories(tmp_path):
    (tmp_path / "9.0.0").mkdir()  # no json inside
    (tmp_path / "9.1.1").mkdir()
    (tmp_path / "9.1.1" / "baseline.json").write_text("{}")

    assert matrix.captured_versions(tmp_path) == {"9.1.1"}


def test_captured_versions_of_a_missing_directory(tmp_path):
    assert matrix.captured_versions(tmp_path / "nope") == set()


def test_releases_unreachable_on_this_python_are_skipped(tmp_path):
    releases = [
        make_release("6.0.0", requires=">=3.5", pythons=("3.8", "3.9")),
        make_release("9.1.1", requires=">=3.10", pythons=("3.12",)),
    ]

    outstanding = matrix.outstanding(releases, tmp_path, python="3.12")

    assert [r.version for r in outstanding] == ["9.1.1"]
