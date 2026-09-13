def test_runs_first():
    assert True


def test_interrupted():
    """Equivalent to pressing Ctrl-C at this point in the run."""
    raise KeyboardInterrupt


def test_never_runs():
    assert True
