# pytest-hook-atlas

A versioned, multi-scenario visual reference for **pytest's hook execution flow**.

pytest's plugin system is documented well in prose, but the *order and nesting* of
hook calls — what fires inside what, which hooks short-circuit, which replay for
plugins registered later — is hard to hold in your head from reading alone. This
project runs real pytest sessions, records the exact hook call tree via pluggy, and
renders it as a set of diagrams.

**→ [zy1o.github.io/pytest-hook-atlas](https://zy1o.github.io/pytest-hook-atlas/)**

## Want this for your own project?

You want [**hook-atlas**](https://github.com/zy1o/hook-atlas), not this. It traces
and draws any [pluggy](https://pluggy.readthedocs.io/)-based application — your test
suite with your plugins and your `conftest.py`, or tox, or datasette, or anything
else built on pluggy:

```bash
pip install hook-atlas
hook-atlas trace -- pytest -q tests/
hook-atlas draw
# open hook-flow.html
```

This repository is what hook-atlas looks like once it has been told about one
particular application. It is the site, the scenarios and the captured traces —
useful to read, not something to install.

## What is here

- **`scenarios/`** — small pytest projects, each exercising a different shape:
  a plain suite, a `conftest.py` implementing every hook, deliberate edge cases, a
  Ctrl-C, an internal error, a distributed run under `pytest-xdist`.
- **`data/traces/`** — every scenario captured against every pytest release from
  6.0 onward. Committed, so a change in pytest's hook flow arrives as a reviewable
  diff rather than a silently different picture.
- **`src/pytest_hook_atlas/`** — the pytest-specific half: the four phases a run is
  drawn as, where hooks link in pytest's reference, and the pages. Everything
  general lives upstream in hook-atlas.

## What makes it different

- **Traced, not guessed.** Hook calls are captured with pluggy's
  `add_hookcall_monitoring`, so the call tree is exact — including which plugin
  supplied each implementation, in pluggy's real call order.
- **Multiple scenarios.** The flow genuinely changes with your layout, and each
  scenario links back to the code that produced it.
- **Every release from 6.0.** Releases producing an identical flow share one page,
  so a version range with nothing to say does not pretend otherwise.

## How it works

```
scenarios/        small pytest projects + how to invoke them        committed
   |  pytest-hook-atlas capture-missing
data/traces/<pytest-version>/<scenario>.json                        committed
   |  pytest-hook-atlas build
docs/  +  mkdocs.yml                                                generated
   |  mkdocs build
site/                                                               generated
```

Each arrow is a separate step. Rendering reads only the committed traces, so
changing how diagrams look — or how versions are grouped — is a
`pytest-hook-atlas build` away and never needs a pytest run.

## Running it locally

Needs Python 3.11+ and the Graphviz binary, which provides `dot`. Install it with
your platform's package manager (`brew install graphviz`, `choco install graphviz`,
`apt install graphviz`, …) or from
[graphviz.org/download](https://graphviz.org/download/).

```bash
pip install -e ".[dev,docs]"

pytest-hook-atlas build          # render docs/ from the committed traces
mkdocs serve                     # preview at http://127.0.0.1:8000

pytest-hook-atlas targets        # which pytest releases exist, and their state
pytest-hook-atlas linkcheck      # verify every hook -> docs anchor still resolves
pytest                           # the project's own tests
```

Capture is rarely needed — the traces are committed, and the watcher picks up new
pytest releases. If you do need it, `capture-missing` takes `--base-python` for
releases needing an interpreter older than the one you are running; `build
--majors N` chooses how many pytest majors get pages, `0` for all.

Working on both repositories at once:

```bash
pip install -e ../hook-atlas -e ".[dev,docs]"
```

## Licence

MIT
