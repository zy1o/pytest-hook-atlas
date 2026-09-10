# Working on pytest-hook-atlas

Notes for anyone — human or agent — picking this up. It is a prototype, so this
is short and describes decisions actually made rather than aspirations.

## What this is

A site that shows the order and nesting of pytest's hooks, built from traces of
*real pytest runs*. It is documentation, not a library. Nothing is published to
PyPI.

## The pipeline, and why it is separate

```
scenarios/        small pytest projects + how to invoke them        committed
    |  hook-atlas capture-missing      (only the watcher runs this)
data/traces/<pytest-version>/<scenario>.json                        committed
    |  hook-atlas build
docs/  +  mkdocs.yml                                                generated
    |  mkdocs build
site/                                                               generated
```

**Each arrow runs independently, and that is deliberate.** Changing how diagrams
look, how versions group, or what the pages say is a `hook-atlas build` away and
needs no pytest run. The deploy workflow renders from committed traces and
never captures.

Keep it that way. If you find yourself needing to re-capture in order to change
presentation, something has been coupled that should not be.

### Traces are immutable

A trace is a fact about one exact `(pytest, pluggy, Python)` triple. Re-capturing
an existing version against different dependencies would make version-to-version
comparisons meaningless, so `capture-missing` skips what is already on disk.
`--force` exists only to correct a capture made incorrectly, not to refresh one.

There is exactly **one** capture path: a throwaway virtualenv holding exactly
the pytest being captured. Do not add a shortcut for "the version already
installed" — that produced traces that silently differed from the rest.

## Adding a scenario

1. Create `scenarios/<id>/` containing a small pytest project.
2. Add `scenarios/<id>/scenario.toml`:

   ```toml
   id = "nested-conftest"        # must match the directory name
   title = "Nested conftest files"
   order = 3                     # position in the nav
   args = ["-q"]                 # arguments passed to pytest
   summary = "One line, shown in tables."
   description = """
   A paragraph or two. Say what the scenario is *for* - what it makes visible
   that other scenarios do not.
   """
   # generated_conftest = true   # optional: write a conftest implementing
                                 # every hook the target pytest declares
   ```

3. Capture it across every pytest version:

   ```bash
   hook-atlas capture-missing --detailed --keep-going
   ```

   A new scenario makes every existing version incomplete, so this backfills
   it. Expect a few minutes. Existing scenarios get re-traced too, but traces
   are reproducible as whole files, so only the new scenario appears in the
   diff. If unrelated traces show up as modified, something non-deterministic
   has crept into the trace — find it rather than committing the churn.

4. `hook-atlas build && mkdocs serve` to look at it.

**Changing an existing scenario invalidates every trace for it.** The project is
part of the measurement apparatus; alter it and the old traces describe a
different experiment. Re-capture with `--force`.

Scenarios deliberately contain failing and skipped tests: the run-test protocol
takes visibly different paths for those, and the diagrams show it.

## The tracer is standalone on purpose

`src/pytest_hook_atlas/tracer.py` must not import from its own package and must
not use syntax newer than Python 3.8. Capturing pytest 6.0 means running on
Python 3.9, where the rest of this package — which needs 3.11 and `tomllib` —
cannot be installed. Capture copies that one file next to the test project.

A test enforces both constraints.

## Diagrams

One visual channel per dimension, and no more:

- **hue** = which phase a hook belongs to
- **darkness** = how often it was called, log-scaled
- **words beneath the name** = `historic`, `firstresult`, repeat counts

Do not spend colour on anything else without removing something first. Version
differences deliberately have no colour; they are surfaced by grouping instead.

The palette was chosen by simulating dichromatic vision, and every colour
carrying text or a border is pushed until it clears WCAG AA in both themes.
`tests/test_css.py` fails if a palette change breaks either. Do not hand-pick
hues to taste without re-running it.

Colours are emitted as **CSS classes**, never baked into the SVG, so one
rendered diagram serves both themes.

## URLs must not change meaning

Groups are named by their **first** pytest version, and every captured version
gets a page — canonical or an alias pointing at its group. Both rules exist
because groups move: adding a scenario splits them, and backfilling older
releases extends them backwards. Naming by the last version would silently
repoint a published URL at different content.

## House rules

- **Never push to `main`.** Work on a branch and hand over the PR link.
- **Record user-visible changes in `CHANGELOG.md`** under `[Unreleased]`.
  `tests/test_changelog.py` fails a version bump with no entry.
- **Explain *why* in comments**, not what. Most non-obvious code here exists
  because something failed in a specific way; say which.
- **Verify against reality, not against your own output.** Two bugs here
  survived a green build: a stylesheet whose selectors matched nothing, and a
  preview script that rendered a picture proving nothing. "Tests pass and the
  build is clean" is not evidence that a page looks right.

## Commands

```bash
pip install -e ".[dev,docs]"     # needs Python 3.11+ and Graphviz (`dot`)

hook-atlas targets --detailed    # what PyPI has, and what is captured
hook-atlas capture-missing       # trace releases not yet recorded
hook-atlas build                 # render docs/ and mkdocs.yml from traces
hook-atlas linkcheck             # verify every hook -> docs anchor resolves

mkdocs serve                     # preview
pytest && ruff check .           # the CI jobs
```
