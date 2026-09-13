"""Generates a dummy implementation for all pytest hooks as found
in pytest hookspec.
"""

import inspect

import _pytest.hookspec as hs


def _spec_opts(hook_name):
    """pluggy stores hookspec options on the function as <project>_spec."""
    opts = getattr(getattr(hs, hook_name, None), "pytest_spec", None)
    return opts if isinstance(opts, dict) else {}


def is_deprecated(hook_name) -> bool:
    """Does implementing this hook at all raise a deprecation warning?

    pytest turns its own removal warnings into errors, so a conftest that
    implements a deprecated hook fails to import and takes the whole run with
    it. pytest 8.0 did this for pytest_cmdline_preparse.
    """
    return _spec_opts(hook_name).get("warn_on_impl") is not None


def deprecated_args(hook_name) -> set:
    """Arguments that cannot be named in an implementation without warning.

    Same trap, one level down: pytest 9.0 errors on `path`, which it was in the
    middle of replacing with `file_path`. Accepting the argument is enough to
    fail; the implementation need never use it.
    """
    return set(_spec_opts(hook_name).get("warn_on_impl_args") or ())


def get_hooks() -> list:
    """Hooks a conftest can implement without tripping a deprecation error."""
    return [hook for hook in dir(hs) if hook.startswith("pytest_") and not is_deprecated(hook)]


def skipped_hooks() -> list:
    """Deprecated hooks left out, so a page can say what was excluded."""
    return [hook for hook in dir(hs) if hook.startswith("pytest_") and is_deprecated(hook)]


def get_hook_implementation(hook_name: str) -> str:
    """Returns string with code (implementation) for a given hook
    name. Each implementation opens a text file and appends data
    with information on the hook"""

    hookspec_item = getattr(hs, hook_name, None)
    if not hookspec_item:
        return ""
    args_dict = inspect.signature(hookspec_item).parameters
    unusable = deprecated_args(hook_name)

    str_args = ", ".join(arg for arg in args_dict if arg not in unusable).strip(",")
    hook_impl_str = f"""
@pytest.hookimpl()
def {hook_name}({str_args}):
    with open("hooks_order.txt", "a+") as hooks_file:
        hooks_file.write("{hook_name}\\n")

        """
    return hook_impl_str


def get_conftest_file() -> str:
    """Returns contents of a conftest.py with all hooks
    implemented"""
    all_hooks = get_hooks()

    conftest_content = "import pytest\n\n"
    for hook in all_hooks:
        conftest_content += get_hook_implementation(hook)

    return conftest_content


if __name__ == "__main__":
    print(get_conftest_file())
