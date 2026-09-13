def pytest_collection_modifyitems(session, config, items):
    """Raise where pytest does not expect it, to force an internal error."""
    raise RuntimeError("a hook implementation raised during collection")
