# Working on pytest-hook-atlas

Notes for anyone — human or agent — picking this up. It is a prototype, so this
is short and describes decisions actually made rather than aspirations.

## What this is

A site that shows the order and nesting of pytest's hooks, built from traces of
*real pytest runs*. It is documentation, not a library. Nothing is published to
PyPI.

## Two repositories

The engine lives in [hook-atlas](https://github.com/zy1o/hook-atlas) and knows
nothing about pytest: capture, the flow model, grouping, implementers and the
renderers. This repository is the pytest wrapper - phases, documentation links,
scenarios, page copy - plus the traces and the site.

Work on both at once with editable installs:

```bash
pip install -e ../hook-atlas -e ".[dev,docs]"
```

The two commands are `hook-atlas` (the generic tool: `trace`, `draw`, `check`)
and `pytest-hook-atlas` (this one: `build`, `capture-missing`, `linkcheck`,
`targets`). They were both called `hook-atlas` until 2026-09-15, which made
installing both in one environment undefined.

The rule for deciding where something belongs: if it is *about* pytest - its
phases, its hooks, its releases, its documentation - it belongs here. If it
would be just as true of tox or datasette, it belongs upstream. That applies to
tests as much as to code: the flow model, the renderers and the stylesheet are
tested in hook-atlas, against its own palette, because nothing in them is
pytest's. What is tested here is what this repository decides - pytest's four
phases, its documented namespaces, its scenarios and the pages built from them.

`hook-atlas` has a test that fails if the package imports pytest at all.

**The acceptance test for anything moved across is that the generated site is
byte-identical.** Snapshot `docs/`, rebuild, `diff -rq`.

## The pipeline, and why it is separate

```
scenarios/        small pytest projects + how to invoke them        committed
    |  pytest-hook-atlas capture-missing      (only the watcher runs this)
data/traces/<pytest-version>/<scenario>.json                        committed
    |  pytest-hook-atlas build
docs/  +  mkdocs.yml                                                generated
    |  mkdocs build
site/                                                               generated
```

**Each arrow runs independently, and that is deliberate.** Changing how diagrams
look, how versions group, or what the pages say is a `pytest-hook-atlas build` away and
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
Those are xdist's logical worker names, not pids, so they stay stable in a
committed trace. Scenario ids therefore may not contain a dot.

**A worker's name is not its identity.** Under a splitting scheduler
(`loadfile`, `loadscope`, `load`, `worksteal`) the split is reproducible but
which worker draws which half is a race - captured twice in a row, `gw0` and
`gw1` swap flows. So pages group workers by the flow they produced and never
by name, and the fingerprint compares workers as an unordered set. Every
distinct worker flow is drawn in full, however many there are: a real suite
across a dozen workers may genuinely produce a dozen, and that is the thing
worth seeing rather than something to summarise away.

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
   pytest-hook-atlas capture-missing --detailed --keep-going
   ```

   A new scenario makes every existing version incomplete, so this backfills
   it. Expect a few minutes. Existing scenarios get re-traced too, but traces
   are reproducible as whole files, so only the new scenario appears in the
   diff. If unrelated traces show up as modified, something non-deterministic
   has crept into the trace — find it rather than committing the churn.

4. `pytest-hook-atlas build && mkdocs serve` to look at it.

**Changing an existing scenario invalidates every trace for it.** The project is
part of the measurement apparatus; alter it and the old traces describe a
different experiment. Re-capture with `--force`.

Scenarios deliberately contain failing and skipped tests: the run-test protocol
takes visibly different paths for those, and the diagrams show it.

## Lay out the choice, then do what is chosen

When a request is vague, or clear but carries consequences that are not visible
from where it was asked, stop before building and lay out the options: what each
costs, what it rules out later, which you would pick and why. Then let the
person choose.

This is **not** a veto, and not a hurdle to clear before you will cooperate. If
they have heard the tradeoff and still want the thing, build it properly and
build it well - not a hedged version, not a lesser version to make a point. It
is their project. Someone who has weighed a cost and accepted it has done the
thinking; arguing again wastes their time and yours.

The failure this prevents is not "a choice was made that I would not have
made". It is "a choice was made without anyone realising there was one". Two
real examples from this repository:

- `--dist=each` against a splitting scheduler for the xdist scenario. Both are
  defensible, they document different things, and the tradeoff was invisible
  until someone measured which worker drew which tests.
- Renaming the console script. Obviously right in isolation, and a breaking
  change for anyone with it in a script - worth saying out loud, and then
  worth doing.

Keep it short. Options, consequences, a recommendation. Not an essay, and not a
list of every possibility - two or three real ones, honestly compared.

This is a different pause from "Stop and ask" below. That one is about actions
that cannot be undone. This one is about decisions whose cost lands later.

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

## Capture runs somewhere this package cannot

The tracer is `hook_atlas.tracer`, upstream, and capture copies it as a single
file next to the scenario rather than installing it. That is what lets an old
pytest be captured at all: pytest 6.0 tops out at Python 3.9, and this package
needs 3.11 and `tomllib`.

So `capture-missing` takes `--base-python`, the interpreter to build capture
virtualenvs from. The 6.0 - 7.3 range was captured with a 3.9 fetched by
`uv python install 3.9`, since no current distribution ships one:

```bash
pytest-hook-atlas capture-missing --python 3.9 --base-python "$(uv python find 3.9)"
```

`--python` says which releases to consider; `--base-python` says what to build
them with. A release whose scenarios cannot all run is captured for the ones
that can - see `pytest_versions` under "Adding a scenario".

## Diagrams

The renderer is upstream in `hook_atlas.render`; what follows is the design it
implements, which this site is the reason for. Changing any of it means
changing hook-atlas and checking the site is unmoved.

One visual channel per dimension, and no more:

- **hue** = which phase a hook belongs to
- **darkness** = how often it was called, log-scaled
- **words beneath the name** = `historic`, `firstresult`, repeat counts

Do not spend colour on anything else without removing something first. Version
differences deliberately have no colour; they are surfaced by grouping instead.

The palette was chosen by simulating dichromatic vision, and every colour
carrying text or a border is pushed until it clears WCAG AA in both themes.
`tests/test_css.py` upstream fails if a palette change breaks either, across
every hue the palette can hand out rather than only the four pytest uses. Do
not hand-pick hues to taste without re-running it.

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
- **Traces are kept, not pruned.** Retention governs what is *rendered* -
  `build --majors N`, default four - and every capture stays committed
  regardless, so widening the window and rebuilding brings old releases back
  with no re-capture. The working tree is large and that is fine: it is
  repetitive JSON, and the whole history packs to well under a megabyte, which
  is what a clone actually transfers. Measure `git count-objects -vH` before
  worrying about it.
- **The version number is the user's call.** Never bump, tag or publish because
  it seems due. Before agreeing to a proposed number, read the `[Unreleased]`
  entries: they say whether what has accumulated is breaking, a feature or a
  fix. If the number disagrees with them - a patch bump over a renamed command,
  say - say so once, plainly, and ask. Departing from semver deliberately is
  fine; departing from it by accident is not. Keep `version` in
  `pyproject.toml` and `__version__` in `src/pytest_hook_atlas/__init__.py` in
  step; a test enforces it.
- **After a change, go and read what describes it.** Not "update the docs if
  you think of it" - open them and check. The prose here does not fail a test
  when it becomes untrue; it just quietly starts lying, and the person it lies
  to is whoever arrives next.

  The hand-written surfaces are `README.md`, this file, `TODO.md`, and the page
  copy and `DESIGN_NOTES` inside `build.py` (which become `docs/design-notes.md`).
  Everything else under `docs/` is generated and needs no attention.

  What triggers a read-through: renaming or removing a command or flag; moving
  code between this repository and hook-atlas; changing what a capture records,
  how versions group, or what a page shows; anything that makes a sentence
  somewhere start with "this repository contains" and be wrong. The whole
  engine moved out and `README.md` still described the old arrangement for
  days, which is exactly the shape of it.
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
- **Do not write down numbers that expire.** Line numbers, file sizes, byte
  counts, ratios, percentages, timings, "N of M releases" - all true when
  written and wrong a few commits later. A stale number is worse than none,
  because it gets believed and acted on: a `TODO.md` entry here promised that
  hoisting one block would take "roughly a third off the trace size", and when
  it was finally measured it was a few percent - an entry that would have sent
  whoever picked it up at the wrong thing. Say what to do and why it matters,
  describe the relationship rather than the figure, and let whoever picks it up
  measure it then. If the measurement *is* the point, write down how to reproduce it
  instead of what it said.

  This applies to living documents - `TODO.md`, `AGENTS.md`, `README.md`, code
  comments. `CHANGELOG.md` entries and commit messages are different: they
  describe a moment that has already passed, so a number in them stays true.
- **Verify against reality, not against your own output.** Two bugs here
  survived a green build: a stylesheet whose selectors matched nothing, and a
  preview script that rendered a picture proving nothing. "Tests pass and the
  build is clean" is not evidence that a page looks right.

## Commands

```bash
pip install -e ".[dev,docs]"     # needs Python 3.11+ and Graphviz (`dot`)

pytest-hook-atlas targets --detailed    # what PyPI has, and what is captured
pytest-hook-atlas capture-missing       # trace releases not yet recorded
pytest-hook-atlas build                 # render docs/ and mkdocs.yml from traces
pytest-hook-atlas linkcheck             # verify every hook -> docs anchor resolves

mkdocs serve                     # preview
pytest && ruff check .           # the CI jobs
```
