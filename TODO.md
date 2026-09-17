# What's next

Rough order of value, not a commitment. Anything here is fair game to pick up.

Pointing this at your own project - the idea most of this list used to circle -
is [hook-atlas](https://zy1o.github.io/hook-atlas/), and is done. What is left
here is about the hosted site.

## Capture the three hooks we attach too late to see

Every hook pytest declares is observed on the site except `pytest_cmdline_parse`
- and that is no longer a fact about pytest, which is how this entry used to
read. It is a fact about how *we* attach.

Capture loads a pytest plugin, so the earliest it can reach the plugin manager
is `pytest_addoption`, by which time `pytest_cmdline_parse`, `pytest_addhooks`
and `pytest_addoption` itself have already been called. hook-atlas's `watch()`
wraps `PluginManager.__init__` instead, which is before pytest calls anything,
and it records all three - verified.

Switching capture to `watch()` would take the site to every hook pytest
declares. What makes it a decision rather than a patch: it changes every trace,
so it needs a re-capture of all 52 releases and a schema bump, and the new
hooks appear at a level no phase currently anchors. Worth doing together with
the caller capture below, which forces the same re-capture.

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

Needs a schema bump - 3 is already spent on recording the traced application
and its version - and a re-capture of every release. The builder must tolerate
older traces so a half-migrated state still builds. Best done in the same pass
as the prologue hooks above, which force the same re-capture.

## Smaller things

- The changes page compares hook *sets*, so a pure reordering reports "same
  hooks, different order" without saying what moved.
