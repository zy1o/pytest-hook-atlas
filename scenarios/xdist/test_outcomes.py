import pytest


def test_fails():
    """A failure has to be serialised by a worker and unpacked by the controller."""
    assert {"a": 1} == {"a": 2}


@pytest.mark.skip(reason="skips travel between processes too")
def test_skipped():
    pass


def test_passes():
    assert True
