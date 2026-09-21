# Changelog

Newest first, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [semantic versioning](https://semver.org/).

What is versioned is the site and the tooling that builds it, not a library API.
Captured traces are never rewritten, so a version bump changes how the atlas is
built or presented, never what was observed.

## [Unreleased]

### Changed

- The flow, renderer and stylesheet tests move to
  [hook-atlas](https://github.com/zy1o/hook-atlas), which is where that code
  lives. They were left behind by the extraction, so this project was testing
  somebody else's package while that package shipped nearly untested.

### Added

- A scenario with no pages for the oldest releases says why on its index. The
  xdist scenario starts at pytest 7.0 because the pytest-xdist it pins needs
  it; unexplained, that read as a gap rather than a limit.
- The site and the README point at
  [hook-atlas](https://github.com/zy1o/hook-atlas) for tracing your own project.
  This repository is the pytest-specific half - scenarios, traces and pages -
  and is worth reading rather than installing.
- pytest 6.0 through 7.3 are captured, so the atlas now covers every release
  from 6.0 onward. They need an interpreter older than this package can run
  on - 6.0 tops out at Python 3.9 - so `capture-missing` takes a
  `--base-python` to build capture environments from.
- `build --majors N` chooses how many pytest majors get pages, with `0` for all
  of them. Traces are never dropped, so the window can be widened and the site
  rebuilt at any time without re-capturing anything.
- Scenarios declare which pytest releases they support. The xdist scenario
  needs pytest 7, and is now skipped for older releases deliberately and
  visibly rather than by accident.

### Fixed

- Pages no longer link hooks their reference does not document. pytest 6.0 and
  6.1 have no published documentation, so those pages fall back to `stable`,
  where hooks pytest has removed since do not exist - and the links 404ed.
  `linkcheck` now asks the same question the build asks, rather than checking
  links the site does not emit, and treats an unreachable page as a fetch
  failure rather than a dead link.

- A capture is refused when the environment does not hold the pytest that was
  asked for. Cheap insurance against a trace filed under one version while
  describing another - pip itself refuses the obvious version conflicts.
- `linkcheck` read the pytest version from a trace field that only schema 2
  traces have.

## [1.2.0] - 2026-09-16

### Changed

- **Breaking:** the command is now `pytest-hook-atlas build` rather than
  `hook-atlas build`. `hook-atlas` belongs to the generic tool, which gained its
  own `trace`, `draw` and `check`; both packages previously declared the same
  console script, so installing them together left which one you got undefined.
  A minor rather than a major version because nothing here has ever been
  published - the rename reaches no installed copy but our own.
- The tracing and drawing move to [hook-atlas](https://github.com/zy1o/hook-atlas),
  a package that knows nothing about pytest and can be pointed at tox, devpi or
  anything else built on pluggy. What stays here is what makes this pytest's
  atlas: the four phases, the documentation links, the scenarios and the pages.
  The generated site is byte-identical across the move.

## [1.1.0] - 2026-09-13

### Added

- Traces record which plugin declared each set of hookspecs, and at what
  version, so a capture can say which xdist - or which project - produced it.
  Read from `__version__` or stdlib metadata, never by adding a dependency to
  the environment being measured.
- An `xdist` scenario, drawn once per process - the controller never collects
  or runs a test, and only it sees the report-serialization hooks. Workers are
  grouped by the flow they produced, not by name: under a splitting scheduler
  `gw0` and `gw1` swap flows between captures, so a name is a race, not an
  identity. Every distinct worker flow is drawn in full, however many there are.
- Overview columns start at the same height. A cluster's label is two lines
  when its hook has semantics to show and one when it does not, and that
  difference was landing on the column top.
- Each diagram says which command produced it, per process. A worker's is
  empty, because xdist starts it over execnet rather than from a command line.
- Long repetitive stretches fold when drawn: one cycle, then a dashed box
  naming the hooks it stands for. The xdist controller's run loop is a hundred
  steps of reports arriving in whatever order workers finish, so it collapses
  to nothing and rendered seven thousand pixels tall. Never fingerprinted.
- Scenarios can run across several processes. Each writes its own trace,
  named `<scenario>.<process>.json` after xdist's logical worker names, and a
  scenario can declare the packages its capture virtualenv needs. Groundwork
  for the xdist scenario, where the controller and workers see genuinely
  different things - the controller never collects or runs a test.
- Hookspecs are read from the live plugin manager rather than by importing
  `_pytest.hookspec`, so hooks a *project* declares are described too - pytest
  contributes 52, pytest-xdist adds 12, and any conftest or plugin calling
  `add_hookspecs` contributes its own. Traces record which module declared each
  hook, and hooks pytest did not declare render without a documentation link
  rather than with a dead one. Trace schema is now 2.
- Three scenarios reaching hooks no other scenario touched: `edge-cases`
  (assertion comparison and assertion-pass, deselection, string `skipif`
  conditions, the report header, both debugger hooks), `interrupted` (a run
  stopped by Ctrl-C) and `internal-error` (a hook implementation raising during
  collection). Coverage rises from 40 of pytest's 52 declared hooks to 49.
- Scenarios declare what they expect - which hooks they exist to reach, whether
  the session completes, and any minimum hook count. Nothing in the tooling
  imposes a minimum: a run that dies in its first hookimpl is drawn as it
  happened.
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

- Long stretches sometimes folded to nothing, drawing the xdist controller at
  14530pt. A hook that ends a stretch rather than belonging to it -
  `pytest_testnodedown`, once per worker - kept the whole stretch drawn.
- Worker sections sorted `gw10` before `gw2`.
- The page sweep only looked at single-process pages, so nothing checked the
  xdist pages it was written to cover.
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

[Unreleased]: https://github.com/zy1o/pytest-hook-atlas/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/zy1o/pytest-hook-atlas/releases/tag/v1.2.0
[1.1.0]: https://github.com/zy1o/pytest-hook-atlas/releases/tag/v1.1.0
[1.0.0]: https://github.com/zy1o/pytest-hook-atlas/releases/tag/v1.0.0
