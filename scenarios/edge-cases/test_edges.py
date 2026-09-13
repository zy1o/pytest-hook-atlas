import pytest


def test_passing_comparison():
    """Reaches pytest_assertion_pass, which only fires for passing asserts."""
    assert [1, 2] == [1, 2]


def test_failing_comparison():
    """Reaches pytest_assertrepr_compare - a bare `assert False` does not,
    because there is nothing to compare."""
    assert {"a": 1} == {"a": 2}


@pytest.mark.skipif("1 > 2", reason="a string condition, not a boolean")
def test_string_skipif():
    """A string condition is evaluated, which reaches pytest_markeval_namespace."""


@pytest.mark.deselect_me
def test_deselected():
    """Deselected by -k, which reaches pytest_deselected."""


def test_ok():
    assert True
