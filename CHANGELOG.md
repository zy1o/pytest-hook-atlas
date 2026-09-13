# Changelog

Newest first, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [semantic versioning](https://semver.org/).

What is versioned is the site and the tooling that builds it, not a library API.
Captured traces are never rewritten, so a version bump changes how the atlas is
built or presented, never what was observed.

## [Unreleased]

### Added

- An `edge-cases` scenario reaching seven hooks no other scenario touched:
  assertion comparison and assertion-pass, deselection, string `skipif`
  conditions, the report header, and both debugger hooks. Coverage rises from
  40 of pytest's 52 declared hooks to 47.
- Hook tables name the plugins implementing each hook, in pluggy's call order,
  with full module paths.
- Implementers are reconciled across each page's release range, with footnotes
  giving the deltas where releases disagree - pytest moves implementations
  between its own plugins without changing the flow.
- Implementations are annotated with pluggy's ordering markers -
  `[wrapper]`, `[tryfirst]`, `[trylast]` - so the call order explains itself
  rather than looking arbitrary.
- A toggle to hide pytest's own plugins, leaving what the project under test
  contributes. Only appears where there is something to reveal.
- A sweep over every generated page: all four stages present, each diagram
  rendered and plausibly sized, links live, footnotes resolved, nothing
  swallowed as HTML.

### Fixed

- `every-hook-conftest` was silently broken on pytest 8.0.x and 9.0.x. pytest
  treats its own removal warnings as errors, so the conftest failed to import
  and the run collapsed to five hook calls while the page still claimed every
  hook was implemented. It now suppresses those warnings and implements
  everything the version declares - which revealed that 8.0 still calls the
  deprecated `pytest_cmdline_preparse`, too early for a conftest to serve.
- Implementers were listed in pluggy's storage order, which is the reverse of
  call order, so the table read upside down.
- The plugin filter hid nothing: two rules of equal specificity fought, and the
  later one un-hid what the first had hidden.
- The plugin registered as `<anonymous>` was swallowed as an HTML tag.
- Offline builds emitted unverified documentation links. pytest's own 9.1.x
  docs serve a redirect loop, so they were dead; offline builds now fall back
  to `stable`.
- A `conftest.py` is labelled by its path, since every conftest imports as the
  module `conftest`.
- Long hook names no longer break mid-word in tables.
- Tests no longer depend on, or write into, generated files in the repository.
  `build()` takes a config path, so a build into a temporary directory is
  self-contained.

## [1.0.0] - 2026-09-10

First release. A ground-up rework of `doc_pytest_flow_chart`, which generated a
single flat SVG from a scraped pytest log and had been dormant five years.

### Added

- **Structural capture.** A standalone tracer installs pluggy's
  `add_hookcall_monitoring` and records the exact call tree - order, nesting,
  and which plugin supplied each implementation. Traces are committed JSON.
- **A version matrix.** Releases are discovered from PyPI and captured in a
  throwaway virtualenv holding exactly that pytest. Yanked releases are
  skipped; the Python each needs comes from its Trove classifiers. 29 captured
  (7.3.2 - 9.1.1); 6.0 - 7.3 await older interpreters.
- **Grouping by flow.** Releases producing an identical flow share one page,
  labelled with the range it covers.
- **Scenarios** as a first-class concept: a small pytest project plus how to
  invoke it, each page linking to the code that produced it.
- **Ordered flow diagrams** in Graphviz - phases as columns, steps top to
  bottom, nesting as clusters. Column headings jump to their detail; every hook
  links to its documentation.
- **A weekly watcher** that captures new pytest releases and commits them.
- Pages for [every release](https://zy1o.github.io/pytest-hook-atlas/versions/),
  [what changed](https://zy1o.github.io/pytest-hook-atlas/changes/), and
  [why the diagrams look as they do](https://zy1o.github.io/pytest-hook-atlas/design-notes/).
- A weekly link checker over every hook-to-documentation anchor.

### Changed

- Diagrams show **order**, not just containment. The old design drew only
  "called inside", hiding that setup, call and teardown are each followed by
  their own `makereport` and `logreport`.
- Hook semantics are written in words rather than encoded in node shapes.
- Packaging modernised to a single PEP 621 `pyproject.toml`; Python 3.11+.

### Fixed

- **Documentation links, dead for years.** A stale base URL after pytest moved
  `reference.html`, plus `rstrip("[hook]")` stripping characters rather than a
  suffix, turning `pytest_addhooks` into `pytest_add`. Pinned URLs are now
  verified before use.
- Traces are reproducible as whole files. The throwaway capture directory
  leaked into the recorded command line and conftest plugin names, so every
  capture produced a diff even when nothing had changed.
- Diagram colours are computed for contrast in both themes. The conventional
  palette put two of its four hues at a colour difference of 3.9 under
  deuteranopia - effectively identical.

### Removed

- The `pytest --debug` log scraper, superseded by structural capture.
- Cookiecutter scaffolding: `setup.py`, `setup.cfg`, `MANIFEST.in`, `tox.ini`,
  `Makefile`, and the unused Sphinx tree.

[Unreleased]: https://github.com/zy1o/pytest-hook-atlas/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/zy1o/pytest-hook-atlas/releases/tag/v1.0.0
