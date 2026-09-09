"""A small suite exercising the ordinary shape of a pytest run.

Deliberately mixed: parametrisation, a yield fixture, a finalizer fixture, a
skip, a failure, and warnings raised at two different points. Each of those
pulls a different set of hooks into the trace, and the failure and skip take
visibly different paths through the runtest protocol.
"""

import warnings

import pytest


@pytest.fixture
def fixture_yield():
    print("setup fixture")
    yield "yielding"
    print("finalize fixture")


@pytest.fixture()
def fixture_finalizer(request):
    def finalizer():
        return "finalizer"

    request.addfinalizer(finalizer)
    return "actual fixture with explicit finalizer"


# Raised at import time, so it lands in pytest_collection's warning batch.
# pytest wraps five hooks in warnings.catch_warnings(record=True) and replays
# the whole batch from a finally block once the wrapped phase ends - so
# pytest_warning_recorded marks a phase boundary, not the moment of the warning.
warnings.warn("collected-time warning from the scenario module", UserWarning, stacklevel=2)


@pytest.mark.parametrize("param1", range(5))
def test_me_one(param1, fixture_yield):
    assert True


def test_fail_intentionally(fixture_finalizer):
    assert False


@pytest.mark.skip()
def test_skip():
    pass


def test_warns_during_the_call_phase():
    """Puts a warning in pytest_runtest_protocol's batch rather than collection's."""
    warnings.warn("runtest-time warning from the scenario", UserWarning, stacklevel=2)
    assert True
