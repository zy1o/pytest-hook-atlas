# What's next

Rough order of value, not a commitment. Anything here is fair game to pick up.

## Point it at your own project

`hook-atlas trace <path>` — run the tracer against an arbitrary test suite and
build a local atlas of *its* hook flow, plugins and all.

This is the idea the project has been circling. The reference site shows how
pytest behaves in scenarios we chose; this would show how it behaves in *your*
project, with your conftests and your plugins interacting. `--debug` already
gives you the log; the value here is the picture, and a picture of the thing
you actually run.

Most of the machinery exists. The tracer is standalone and copied in place
precisely so it can run anywhere. What is missing:

- capture without a `scenario.toml`, against the project's own environment
  rather than a provisioned virtualenv
- a build path that copes with a single capture (grouping across one version
  is trivial, but untested)
- a **manual**: how to check the project out, point it at a suite, and read
  the result

Worth checking early: a large suite traces a lot of calls. Consecutive-repeat
collapsing should handle it well - a thousand tests should collapse to a
handful of variants - but nobody has measured it.

## xdist

A scenario running under `pytest-xdist`. The controller and each worker run
different flows, so this needs per-process traces and a merged view. The tracer
already takes its output path from an environment variable for exactly this.

Also the first scenario to bring genuine third-party plugins, which is when the
"hide pytest's own plugins" filter starts earning itself.

## Conftest scoping is flattened

A conftest's hook implementations only apply to items **below its directory**,
but the hook table merges the implementations seen across every call of that
hook. In a project with nested conftests the table therefore lists all of them
against one hook, which reads as though all four run for every test. They do
not.

Confirmed with a four-directory probe: `sub_a/conftest.py` and
`sub_b/conftest.py` both appear under `pytest_runtest_setup`, though neither
runs for the other's tests.

Fixing it means showing implementations per call rather than merged, or marking
which are directory-scoped. Worth solving before the nested-conftest scenario
lands, since that scenario exists precisely to show this.

(Related gotcha for whoever writes that scenario: two test files sharing a
basename in sibling directories fail collection with "import file mismatch"
unless the directories have `__init__.py`. Give them distinct names.)

## Record where each hook was called from

Alongside who implements it. Measured at about 4 microseconds per call, and the
caller is usually a single stable site per hook.

Two constraints established while evaluating it:

- **no line numbers.** They move on every release - zero of thirty-eight were
  stable across a major - and would turn the page into a version salad for
  precision nobody needs. Module and function only.
- **it must not reach the fingerprint**, or grouping fragments.

Needs `schema_version` 2 and a re-capture of every release, so it is best
folded into the same re-capture xdist will force. The builder must tolerate
schema 1 traces so a half-migrated state still builds.

## Backfill pytest 6.0 - 7.3

Twenty-four releases that need older interpreters than the watcher runs, so
they need a workflow with a Python matrix. The matrix can be derived from
`hook-atlas targets --detailed`, which already knows which Python each release
supports - no hand-maintained table.

## Smaller things

- Hoist the duplicated `hookspecs` block out of each scenario's trace and store
  it once per pytest version. Roughly a third off the trace size, which is
  around 19 MB today.
- The changes page compares hook *sets*, so a pure reordering reports "same
  hooks, different order" without saying what moved.
