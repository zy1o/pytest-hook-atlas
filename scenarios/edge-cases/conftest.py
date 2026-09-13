def pytest_assertion_pass(item, lineno, orig, expl):
    """Present so pytest enables the hook at all.

    _pytest.assertion checks `ihook.pytest_assertion_pass.get_hookimpls()` and
    only instruments passing assertions when something is listening.
    """
