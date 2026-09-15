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

Hookspec discovery is done: the tracer reads them from the live plugin
manager, so a project's own hooks arrive with their semantics and no list
has to be supplied. Only documentation *links* need a per-project answer,
and `DOCUMENTED_NAMESPACES` in `doclinks.py` is where that goes.

Worth checking early: a large suite traces a lot of calls. Consecutive-repeat
collapsing should handle it well - a thousand tests should collapse to a
handful of variants - but nobody has measured it.

## The last hook

Every hook pytest declares is observed somewhere on the site except one, and
that one is structural rather than a gap worth closing:

- `pytest_cmdline_parse` - structurally unobservable. Monitoring can only be
  installed once a plugin manager exists, and plugins are loaded *inside* this
  call. Confirmed for both `-p` and `pytest11` entry-point plugins.

The two report-serialization hooks pytest never calls itself arrived with the
xdist scenario, which is where reports actually cross a process boundary.

## A second distributed scenario

The `xdist` scenario runs `--dist each`, which gives every worker the whole
suite: workers come out identical, and the race over which worker draws which
half does not arise. The cost is that `each` is the one mode whose *controller*
flow differs from the other four - `loadfile`, `loadscope`, `load` and
`worksteal` all agree with each other.

A scenario under a splitting scheduler would document that common controller,
and would be the only place the site shows more than one worker flow. Today
that path exists and is covered by tests, but no page exercises it.

## Trace pytest's own test suite

A scenario whose subject is pytest testing itself. Interesting because it is the
most demanding thing we could point this at: a real suite with real plugins and
a conftest that does genuine work, rather than the small projects the other
scenarios use.

Expect it to go wrong, and in ways worth knowing about:

- **Self-reference.** hook-atlas already hits this tracing its own tests - the
  tests exercising the tracer manipulate the same module-level recorder the
  outer trace uses, and fail when traced. pytest's suite runs pytest in
  subprocesses constantly (`pytester`), and those are separate processes that
  will not be traced, so what comes back may be a trace of the outer run only.
  That is worth knowing either way, but it is not what someone would assume the
  page was showing.
- **Size.** Thousands of tests is a trace far larger than anything committed
  here, and a diagram far taller. Folding helps; it will not be enough on its
  own, and a scenario that produces an unreadable page is not worth hosting.
- **Reproducibility.** Traces are committed and must be identical across runs.
  A suite that large has more opportunities to differ - ordering, timing,
  whatever happens to be installed.

So: capture it once as an experiment and look at what comes back before
deciding whether it becomes a scenario. The failure modes are the interesting
part even if the page never ships.

A cheaper first step in the same direction: datasette's test suite, which
hook-atlas already traces in CI, and which brings several hookspec sources with
it.

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

Alongside who implements it. Measured as cheap enough not to matter next to the
hook call itself, and the caller is usually a single stable site per hook.

Two constraints established while evaluating it:

- **no line numbers.** They move on every release - zero of thirty-eight were
  stable across a major - and would turn the page into a version salad for
  precision nobody needs. Module and function only.
- **it must not reach the fingerprint**, or grouping fragments.

Needs `schema_version` 3 and a re-capture of every release. The builder must
tolerate older traces so a half-migrated state still builds.

## Backfill pytest 6.0 - 7.3

These releases need older interpreters than the watcher runs, so they need a
workflow with a Python matrix. The matrix can be derived from
`pytest-hook-atlas targets --detailed`, which already knows which Python each release
supports - no hand-maintained table.

## Smaller things

- The changes page compares hook *sets*, so a pure reordering reports "same
  hooks, different order" without saying what moved.
