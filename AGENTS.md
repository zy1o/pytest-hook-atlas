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

A scenario may declare `requires` (packages installed into its capture
virtualenv, which is how it brings a plugin) and `distributed = true` (it runs
across several processes). A distributed scenario writes one trace per process,
named `<scenario>.<process>.json` - `controller`, `gw0`, `gw1` under xdist.
Those are xdist's logical worker names, not pids, so they stay meaningful in a
committed trace. Scenario ids therefore may not contain a dot.

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

## The tool imposes no minimums

Nothing in capture or build requires a run to reach a certain number of hooks,
or to complete. A session that dies in its first hookimpl should be drawn
exactly as it happened - that is the whole point of pointing this at a real
project.

Expectations belong to scenarios, not to the tooling. `scenario.toml` carries
`expects` (hooks this scenario exists to reach), `complete_run` (whether the
session finishes) and `min_hooks` (a floor, zero meaning none). The test suite
checks the scenarios *we host* against their own declarations; it does not
impose a rule on anyone pointing the tracer at their own suite.

## Never add anything to the environment being measured

The capture virtualenv holds exactly pytest and whatever a scenario declares in
`requires`. Nothing else. The tracer is copied in as a single file rather than
installed, so it must never acquire a dependency of its own.

This is why trace provenance reads a package's `__version__`, falling back to
stdlib `importlib.metadata`, instead of depending on the `importlib-metadata`
backport with an environment marker. The backport would be more convenient and
is almost certainly harmless - but installing anything into the environment
under observation is a habit worth not having, because the one time it matters
will not announce itself. It matters more once this is pointed at someone
else's project: observing it should not mean installing into it.

## Pinning a scenario's plugins

A scenario's `requires` are pinned, not floated. Traces are immutable and the
watcher only captures pytest releases it does not have, so a floating plugin
would never trigger a re-capture - it would simply freeze at whatever pip
resolved on the day, and the page would show an ageing version without saying
so. Pinning makes the version a deliberate, reviewable fact.

`pytest-xdist` is pinned after checking its history: across 19 releases from
2.0 there are three distinct hookspecs, and none since 2.3.0 in 2021 - fifteen
consecutive releases identical, with no removals or signature changes. A bump
should be rare.

**If a pinned version needs changing**, open a pull request bumping it - or an
issue, if you would rather it were discussed first. The re-capture and the
resulting diff are the point: they show whether the flow moved.

Unpinned is right for the *standalone tool*, where someone pointing it at their
own project should get whatever they already have installed. Pinning applies to
the scenarios hosted here.

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
- **Keep changelog entries to a line or two.** One bullet per change, leading
  with what changed; the interesting *why* belongs in a trailing clause, not a
  paragraph. Entries had drifted into three-paragraph explanations nobody was
  going to read. If a change genuinely needs more room, the commit message is
  the place for it - that is what it is for, and the changelog links to it.
- **Explain *why* in comments**, not what. Most non-obvious code here exists
  because something failed in a specific way; say which.
- **Test in an environment that matches CI**, which means a *clean clone*.
  `docs/` and `mkdocs.yml` are generated and gitignored, so a working copy has
  them and CI does not. Tests that read either passed here and failed there.
  Tests must also write nothing into the repository - `build()` takes a
  `config_path` for exactly that reason. Verify with:

  ```bash
  git clone . /tmp/check && cd /tmp/check
  python -m venv .venv && ./.venv/bin/pip install -e ".[dev,docs]"
  ./.venv/bin/pytest && git status --short   # must be empty
  ```
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
