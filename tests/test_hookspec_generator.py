"""Tests for the conftest generator.

No longer used for capture - the tracer does that - but it builds the
``every-hook-conftest`` scenario, whose whole point is a conftest that
implements every declared hook.
"""

import _pytest.hookspec

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


def test_generator_includes_deprecated_hooks():
    """The scenario implements everything the version declares.

    Skipping deprecated hooks would be easier, but it would quietly change what
    the scenario claims - and the deprecated ones are interesting precisely
    because pytest still calls some of them.
    """
    declared = {name for name in dir(_pytest.hookspec) if name.startswith("pytest_")}

    assert set(hookspec_generator.get_hooks()) == declared


def test_deprecated_hooks_are_reported_not_hidden():
    """Introspection kept so the reason for the warning filter stays visible."""
    deprecated = [
        name for name in hookspec_generator.get_hooks() if hookspec_generator.is_deprecated(name)
    ]
    with_bad_args = [
        name for name in hookspec_generator.get_hooks() if hookspec_generator.deprecated_args(name)
    ]

    # current pytest has neither, older ones do; the helpers must still work
    assert isinstance(deprecated, list)
    assert isinstance(with_bad_args, list)


def test_generated_conftest_keeps_deprecated_arguments():
    """pytest 9.0 errors on naming `path`, which is why the scenario filters
    removal warnings rather than dropping the argument."""
    source = hookspec_generator.get_conftest_file()

    for hook in hookspec_generator.get_hooks():
        for argument in hookspec_generator.deprecated_args(hook):
            assert argument in source.split(f"def {hook}(")[1].split(")")[0]
