"""This module contains a set of dummy tests which are
supposed to trigger pytest hooks"""

import pytest


@pytest.fixture
def fixture_yield():
    print("setup fixture")
    yield "yileding"
    print("finalize fixture")


@pytest.fixture()
def fixture_finalizer(request):
    def finalizer():
        return "finalizer"

    request.addfinalizer(finalizer)
    return "actual fixture with explicit finalizer"


@pytest.mark.parametrize("param1", range(5))
def test_me_one(param1, fixture_yield):
    assert True


def test_fail_intentionally(fixture_finalizer):
    assert False


@pytest.mark.skip()
def test_skip():
    pass


@pytest.mark.pytest_deselect
def test_to_be_deselected():
    pass
