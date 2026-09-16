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

Tried on 2026-09-16 against pytest 9.1.1's own `testing/` tree, seven modules,
about a thousand tests. It does not go belly up: the capture completed, the
trace validated, no desyncs, and the overhead was a few percent of wall clock.
So the question is not whether it works.

What it showed instead:

- **The flat default is useless at this scale.** Drawn with no config, a
  thousand tests is a diagram deep into six figures of pixels - nearly two
  hundred screens. It renders, which is the guarantee, but nobody can read it.
- **Phases are what make it readable**, and dramatically so. The same trace
  drawn with pytest's config is four diagrams, the largest of them collection,
  and the run-test protocol is small because variant grouping collapses a
  thousand near-identical protocols into the shapes that actually differ. This
  is the clearest evidence so far that the phase config earns its keep.
- **Memory is the ceiling.** The whole call tree is held until the process
  exits, and it scales with calls. A thousand tests was comfortable; the full
  suite is several times that, and the trace file grows with it. Streaming
  capture stops being an optimisation and becomes the thing that decides whether
  this is possible at all.
- **`pytester` subprocesses are invisible.** Much of pytest's suite runs pytest
  in a child process, and those are not traced - the tracer is process-local.
  What comes back is the outer run only. Honest, but not what a reader would
  assume a page titled "pytest testing itself" was showing, so that would have
  to be said plainly on the page.

To redo the measurement: clone pytest at a tag, `pip install ".[dev]"` alongside
`hook-atlas`, then `hook-atlas trace -- pytest -q testing/test_mark.py ...` over
a few modules, and `hook-atlas draw` the result with and without
`hook-atlas config --example pytest`. Compare the diagram heights.

**So: not a scenario yet.** Streaming capture first, then decide - and if it
does become one, it should be a named subset rather than the whole suite, with
the subprocess caveat on the page.

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

**Done.** Every release from 6.0 is captured.

It did not need the Python matrix this entry used to call for. Every missing
release supports 3.7, 3.8 and 3.9, so one interpreter covers all of them -
`capture-missing --python 3.9 --base-python <path>`, with the interpreter
fetched by `uv python install 3.9` since distributions no longer ship one.

Two things had to change to make it safe rather than merely possible:

- `provision` builds the capture virtualenv from a named interpreter. It used
  to use the one running this package, which needs 3.11 and therefore cannot
  install pytest 6.
- A capture is refused when the environment does not hold the pytest that was
  asked for. pip resolves the whole install at once, so `pytest==6.0.0` next to
  `pytest-xdist==3.8.0` installs pytest 8.4.2 and succeeds - the trace would
  have been filed under 6.0.0 while describing 8.4.2, and nothing downstream
  could have told. Scenarios now declare which releases they support, so xdist
  is skipped for pytest 6 deliberately and said out loud.

## Smaller things

- The changes page compares hook *sets*, so a pure reordering reports "same
  hooks, different order" without saying what moved.
