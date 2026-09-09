# pytest-hook-atlas

A versioned, multi-scenario visual reference for **pytest's hook execution flow**.

pytest's plugin system is documented well in prose, but the *order and nesting* of hook
calls — what fires inside what, which hooks short-circuit, which replay for plugins
registered later — is hard to hold in your head from reading alone. This project runs
real pytest sessions, records the exact hook call tree via pluggy, and renders it as a
set of diagrams.

**→ [zy1o.github.io/pytest-hook-atlas](https://zy1o.github.io/pytest-hook-atlas/)**

## What makes it different

- **Traced, not guessed.** Hook calls are captured with pluggy's
  `add_hookcall_monitoring`, so the call tree is exact — including which plugin
  supplied each implementation.
- **Multiple scenarios.** The flow genuinely changes with your layout: nested
  `conftest.py` files, an installed plugin, `xdist` workers. Each scenario gets its own
  diagrams, linked to the source that produced them.
- **Multiple pytest versions.** Diagrams are captured per pytest release, so you can see
  what changed between versions.

## How it works

```
scenarios/           small pytest projects + how to invoke them   (committed)
   |  hook-atlas capture
data/traces/<pytest-version>/<scenario>.json                       (committed)
   |  hook-atlas build
docs/                generated MkDocs sources                      (generated)
   |  mkdocs build
site/                                                              (generated)
```

Traces are committed, so a change in pytest's hook flow shows up as a
reviewable diff rather than a silently different picture.

Each arrow is a separate step. Rendering reads only the committed traces, so
changing how diagrams look — or how versions are grouped — means re-running
`hook-atlas build` alone. Capture is never needed to change the output.

## Running it locally

Needs Python 3.11+ and the Graphviz binary, which provides `dot`. Install it
with your platform's package manager (`brew install graphviz`,
`choco install graphviz`, `apt install graphviz`, …) or from
[graphviz.org/download](https://graphviz.org/download/).

```bash
pip install -e ".[dev,docs]"

hook-atlas capture     # run every scenario under the tracer
hook-atlas build       # render docs/ from the captured traces
mkdocs serve           # preview at http://127.0.0.1:8000

hook-atlas linkcheck   # verify every hook -> docs anchor still resolves
pytest                 # the project's own tests
```

## Status

Under active reconstruction. Scenarios for nested conftests, an installed
plugin, and `xdist` are still to come, as is capture across multiple pytest
versions.

## Licence

MIT
