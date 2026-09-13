import pytest


@pytest.mark.parametrize("n", range(3))
def test_alpha_passes(n):
    assert n >= 0


def test_alpha_fixture(tmp_path):
    assert tmp_path.exists()
