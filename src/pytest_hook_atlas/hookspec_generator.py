"""Generates a dummy implementation for all pytest hooks as found
in pytest hookspec.
"""

import inspect

import _pytest.hookspec as hs


def get_hooks() -> list:
    """Returns a list of pytest hooks"""
    return [hook for hook in dir(hs) if hook.startswith("pytest_")]


def get_hook_implementation(hook_name: str) -> str:
    """Returns string with code (implementation) for a given hook
    name. Each implementation opens a text file and appends data
    with information on the hook"""

    hookspec_item = getattr(hs, hook_name, None)
    if not hookspec_item:
        return ""
    args_dict = inspect.signature(hookspec_item).parameters

    str_args = ", ".join([arg for arg in args_dict]).strip(",")
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
