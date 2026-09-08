"""Generate the MkDocs source tree from captured traces.

Everything under ``docs/`` is generated and gitignored; the committed inputs are
``scenarios/`` (the code) and ``data/traces/`` (the captures).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from . import analysis, doclinks
from .render import dot, mermaid
from .scenarios import Scenario, discover

LANGUAGE_BY_SUFFIX = {".py": "python", ".toml": "toml", ".ini": "ini", ".cfg": "ini"}


def _fence(path: Path) -> str:
    language = LANGUAGE_BY_SUFFIX.get(path.suffix, "")
    body = path.read_text().strip()
    return (
        f'??? example "{path.name}"\n\n    ```{language}\n'
        + "\n".join(f"    {line}" if line else "" for line in body.splitlines())
        + "\n    ```\n"
    )


def _provenance(scenario: Scenario, trace: dict[str, Any]) -> str:
    """The 'inspect the code that generated this' block.

    Diagrams differ between scenarios; that is the whole point, so a reader has
    to be able to get from any diagram to the exact project that produced it.
    """
    environment = trace["environment"]
    invocation = " ".join(["pytest", *scenario.args])
    lines = [
        "## How this was produced\n",
        f"- **Source:** [`scenarios/{scenario.id}/`]({scenario.source_url})"
        " - the project this diagram was traced from",
        f"- **Invocation:** `{invocation}`",
        f"- **pytest** {environment['pytest']}, "
        f"**pluggy** {environment['pluggy']}, "
        f"**Python** {environment['python']}",
        f"- **Observed:** {trace['stats']['total_calls']} hook calls, "
        f"{trace['stats']['unique_hooks']} distinct hooks\n",
    ]
    for path in scenario.source_files():
        lines.append(_fence(path))
    return "\n".join(lines)


def _hook_table(graph: analysis.HookGraph, base_url: str) -> str:
    rows = ["| Hook | Calls | Semantics | Implemented by |", "| --- | --: | --- | --: |"]
    for name in sorted(graph.hooks):
        hook = graph.hooks[name]
        semantics = {
            "plain": "",
            "historic": "historic",
            "firstresult": "firstresult",
            "both": "historic, firstresult",
        }[hook.semantics]
        url = doclinks.hook_url(name, base_url)
        rows.append(
            f"| [`{name}`]({url}) | {hook.call_count} | {semantics} | {len(hook.plugins)} |"
        )
    return "\n".join(rows)


def scenario_page(
    scenario: Scenario, trace: dict[str, Any], assets: Path, verify_links: bool = True
) -> str:
    # verified by default: an unverified pinned URL can point at docs that
    # were never built, which is how the links broke last time
    base_url = doclinks.resolve_base_url(trace["environment"]["pytest"], verify=verify_links)
    parts = [f"# {scenario.title}\n", f"{scenario.summary}\n", f"{scenario.description}\n"]
    parts.append(_provenance(scenario, trace))

    for graph in analysis.phase_graphs(trace):
        parts.append(f"## {graph.title}\n")
        parts.append(f"{graph.description}\n")
        parts.append(mermaid.render_block(graph, base_url, direction="TB") + "\n")

    full = analysis.full_graph(trace)
    svg_name = f"{scenario.id}-full.svg"
    dot.render_svg(full, base_url, assets / svg_name)
    parts.append("## The full map\n")
    parts.append(
        "Every hook observed in this scenario, in one graph. Rendered with "
        "Graphviz, which stays readable at this size where Mermaid does not.\n"
    )
    parts.append(f"![Full hook flow for {scenario.title}](../assets/{svg_name})\n")

    if scenario.generated_conftest:
        blind = analysis.conftest_blind_spots(full)
        if blind:
            parts.append("## Hooks a conftest cannot serve\n")
            parts.append(
                "This scenario's `conftest.py` implements **every** hook pytest "
                "declares. The hooks below still fired *without* it: the "
                "implementation was registered and never invoked, because the "
                "conftest had not been imported yet when the hook ran, or sits "
                "below the level the hook applies to.\n"
            )
            parts.append(
                "This is the practical reason some behaviour can only be "
                "provided by a plugin, never by a `conftest.py`.\n"
            )
            for name in blind:
                url = doclinks.hook_url(name, base_url)
                parts.append(f"- [`{name}`]({url})")
            parts.append("")

    parts.append("## Hooks observed\n")
    parts.append(_hook_table(full, base_url) + "\n")
    return "\n".join(parts)


def index_page(scenarios: list[tuple[Scenario, dict[str, Any]]]) -> str:
    environment = scenarios[0][1]["environment"] if scenarios else {}
    parts = [
        "# pytest hook atlas\n",
        "A visual reference for the order and nesting of **pytest's hooks** - "
        "captured from real pytest runs, not transcribed from prose.\n",
        "Each diagram below is traced with pluggy's hook monitoring, so it "
        "reflects what pytest actually did, including which plugin supplied "
        "each implementation.\n",
        "## Scenarios\n",
        "The flow genuinely changes with your project layout. Every scenario "
        "links to the code it was produced from.\n",
        "| Scenario | What it shows | Hook calls |",
        "| --- | --- | --: |",
    ]
    for scenario, trace in scenarios:
        parts.append(
            f"| [{scenario.title}](scenarios/{scenario.id}.md) "
            f"| {scenario.summary} | {trace['stats']['total_calls']} |"
        )
    parts.append("\n## How to read the diagrams\n")
    parts.append(mermaid.LEGEND)
    parts.append(
        "\nNode shape carries meaning rather than colour, so the diagrams "
        "survive dark mode, printing and colour-blindness.\n"
    )
    parts.append("## Captured with\n")
    if environment:
        parts.append(
            f"pytest **{environment['pytest']}**, pluggy **{environment['pluggy']}**, "
            f"Python **{environment['python']}**.\n"
        )
    return "\n".join(parts)


def build(
    repo_root: Path, docs_dir: Path, traces_dir: Path, verify_links: bool = True
) -> list[Path]:
    """Render every captured scenario into ``docs_dir``. Returns pages written."""
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    assets = docs_dir / "assets"
    (docs_dir / "scenarios").mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)

    captured: list[tuple[Scenario, dict[str, Any]]] = []
    for scenario in discover(repo_root / "scenarios"):
        trace_path = traces_dir / f"{scenario.id}.json"
        if not trace_path.exists():
            continue
        captured.append((scenario, analysis.load_trace(trace_path)))

    written = []
    for scenario, trace in captured:
        page = docs_dir / "scenarios" / f"{scenario.id}.md"
        page.write_text(scenario_page(scenario, trace, assets, verify_links))
        written.append(page)

    index = docs_dir / "index.md"
    index.write_text(index_page(captured))
    written.append(index)
    return written
