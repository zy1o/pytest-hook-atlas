# Changelog

All notable changes to this project are recorded here, newest first.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project uses [semantic versioning](https://semver.org/). Note that the
thing being versioned is the *site and the tooling that builds it*, not a
library API - nothing here is published to PyPI.

Captured traces are never rewritten, so a version bump changes how the atlas is
built or presented, never what was observed.

## [Unreleased]

### Added

- Every hook's table now names the **plugins that implement it** rather than
  counting them. pytest implements most of itself as plugins, so this shows
  that `pytest_runtest_setup` is served by `runner`, `skipping`,
  `capturemanager` and others.
- Implementers are reconciled across the releases a page covers. They can
  differ within a range even when the flow does not - pytest moved
  `pytest_cmdline_main` from its `python` plugin to `fixtures` at 8.2.0, and
  dropped `python_path` at 8.4.0, neither of which changed what happens. Where
  a range disagrees, the table shows the newest answer and a footnote gives the
  rest, so the page never misdescribes the releases it covers.

- Implementers are listed **in pluggy's call order**, one per line, with the
  full name of what implements them - `_pytest.capture.CaptureManager` rather
  than `capturemanager`, with the registered plugin name alongside when the two
  differ.
- Footnotes describing an implementer change name the full module - "gained `_pytest.unraisableexception`" says where to look, where the bare plugin name only says what it is called.

### Fixed

- Implementers were listed in pluggy's *storage* order, which is the reverse of
  the order it calls them. The table read upside down: `trylast`
  implementations appeared first.
- The plugin registered as `<anonymous>` was written bare into a table cell and
  swallowed as an HTML tag, so that row began with a stray comma.
- An offline build (`--no-verify-links`) emitted an unverified pinned
  documentation URL. pytest's own 9.1.x docs currently serve a redirect loop, so
  those links were dead - the exact failure the link checking exists to prevent.
  Offline builds now fall back to `stable`.
- Long hook names no longer break mid-word in tables.

This needed no re-capture: the data was already in every committed trace.

## [1.0.0] - 2026-09-10

First real release. A ground-up rework of `doc_pytest_flow_chart`, which
generated a single flat SVG from a scraped pytest log and had been dormant for
five years.

### Added

- **Structural capture.** A standalone tracer plugin installs pluggy's
  `add_hookcall_monitoring` and records the exact hook call tree: the order,
  what ran inside what, and which plugin supplied each implementation. Traces
  are versioned JSON, committed, and byte-reproducible.
- **A version matrix.** Every pytest release from 6.0 onward is discovered from
  PyPI and captured in a throwaway virtualenv holding exactly that release.
  Yanked releases are skipped; the Python each release needs is derived from its
  Trove classifiers rather than a hand-maintained table. 29 releases captured
  so far (7.3.2 - 9.1.1); 6.0 - 7.3 await a workflow with older interpreters.
- **Grouping by flow.** Releases producing an identical flow share one page,
  labelled with the range they cover. 29 releases render as 3 pages for the
  baseline scenario and 5 for the every-hook-conftest scenario.
- **Scenarios** as a first-class concept: a small pytest project plus how to
  invoke it, each page linking back to the code that produced it.
- **Ordered flow diagrams** rendered with Graphviz - phases as columns left to
  right, steps top to bottom, nesting as clusters. Column headings jump to that
  phase's detail, and every hook links to its pytest documentation.
- **A weekly watcher** that notices new pytest releases, captures them and
  commits the traces.
- Site pages for [every captured release](https://zy1o.github.io/pytest-hook-atlas/versions/), [what changed between
  them](https://zy1o.github.io/pytest-hook-atlas/changes/), and [why the diagrams look as they do](https://zy1o.github.io/pytest-hook-atlas/design-notes/).
- A link checker, run weekly, that verifies every hook-to-documentation anchor
  still resolves.

### Changed

- Diagrams show **order**, not just containment. The previous design drew only
  "called inside", which hid the thing people most often get wrong: setup, call
  and teardown are each followed by their own `makereport` and `logreport` pair.
- Hook semantics (`historic`, `firstresult`) are written in words beneath each
  hook rather than encoded in node shapes that needed a legend to decode.
- Packaging modernised to a single PEP 621 `pyproject.toml`; Python 3.11+.

### Fixed

- **Hook documentation links, dead for years.** Three separate causes: a stale
  base URL after pytest moved `reference.html`, `rstrip("[hook]")` stripping
  characters rather than a suffix so `pytest_addhooks` became `pytest_add`, and
  a substring filter matching any line containing "hook". Pinned URLs are now
  verified before use, with a documented fallback.
- Captured traces are reproducible as whole files. The throwaway capture
  directory leaked into the recorded command line and into conftest plugin
  names, so every capture produced a diff even when nothing had changed - noise
  in exactly the file whose purpose is that a real change shows up as a
  reviewable diff.
- Diagram colours are computed for contrast in both themes. The palette in use
  was selected by simulating dichromatic vision: the conventional choice put two
  of its four hues at a colour difference of 3.9 under deuteranopia, which is
  effectively indistinguishable.

### Removed

- The `pytest --debug` log scraper, superseded by structural capture.
- Cookiecutter scaffolding: `setup.py`, `setup.cfg`, `MANIFEST.in`, `tox.ini`,
  `Makefile`, and the unused Sphinx documentation tree.

[Unreleased]: https://github.com/zy1o/pytest-hook-atlas/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/zy1o/pytest-hook-atlas/releases/tag/v1.0.0
