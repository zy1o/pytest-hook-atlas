"""Tests for the conftest generator.

No longer used for capture - the tracer does that - but it builds the
``every-hook-conftest`` scenario, whose whole point is a conftest that
implements every declared hook.
"""

from pytest_hook_atlas import hookspec_generator


def test_get_hooks_finds_known_hooks():
    hooks = hookspec_generator.get_hooks()

    assert "pytest_collection_modifyitems" in hooks
    assert "pytest_runtest_setup" in hooks
    assert all(name.startswith("pytest_") for name in hooks)


def test_generated_conftest_reproduces_hook_signature():
    conftest = hookspec_generator.get_conftest_file()

    assert "def pytest_collection_modifyitems(session, config, items)" in conftest


def test_generated_conftest_is_valid_python():
    compile(hookspec_generator.get_conftest_file(), "<generated conftest>", "exec")
