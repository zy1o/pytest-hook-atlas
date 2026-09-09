"""Generate the MkDocs source tree from captured traces.

Everything under ``docs/`` is generated and gitignored; the committed inputs are
``scenarios/`` (the code) and ``data/traces/`` (the captures).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from . import analysis, doclinks, flow
from .render import css, dot
from .scenarios import Scenario, discover

LANGUAGE_BY_SUFFIX = {".py": "python", ".toml": "toml", ".ini": "ini", ".cfg": "ini"}

OUTLINE_DEPTH = 2

LEGEND = """
| In a diagram | Meaning |
| --- | --- |
| a box | one hook call |
| a box inside another | called *during* the enclosing hook |
| an arrow | what happened *next*, in the order the trace recorded |
| `firstresult` | the first non-`None` return wins; later implementations are skipped |
| `historic` | replays for plugins registered later |
| `xN` | the same step repeated N times in a row, collapsed |

Every box links to that hook's entry in the pytest reference documentation.
"""


def _fence(path: Path) -> str:
    language = LANGUAGE_BY_SUFFIX.get(path.suffix, "")
    body = path.read_text().strip()
    indented = "\n".join(f"    {line}" if line else "" for line in body.splitlines())
    return f'??? example "{path.name}"\n\n    ```{language}\n{indented}\n    ```\n'


def _diagram(
    nodes: list[flow.FlowNode],
    hookspecs: dict[str, Any],
    base_url: str,
    phase: str = "startup",
    totals: dict[str, int] | None = None,
) -> str:
    """Inline the SVG so its links stay clickable and CSS can theme it."""
    if not nodes:
        return ""
    svg = dot.render_inline_svg(nodes, hookspecs, base_url, phase, totals)
    return f'<div class="ha-diagram">\n{svg}\n</div>\n'


def _overview(
    trace: dict[str, Any], base_url: str, totals: dict[str, int], depth: int = OUTLINE_DEPTH
) -> str:
    """The whole session as columns: phases left to right, steps top to bottom.

    Depth-limited on purpose. At full depth the collection column alone runs to
    29 nested steps and the page is about two and a half screens; the detail
    lives in the per-phase diagrams below. That collection dwarfs the other
    columns is not imbalance to fix - it is where pytest's complexity is.
    """
    columns = []
    for phase in analysis.PHASES:
        variants = flow.phase_variants(analysis.find_subtrees(trace["calls"], phase.anchors))
        if variants:
            columns.append((phase.key, phase.title, flow.prune(variants[0].flow, depth)))
    if not columns:
        return ""
    svg = dot.to_inline_svg(dot.build_columns(columns, trace["hookspecs"], base_url, totals))
    return f'<div class="ha-diagram">\n{svg}\n</div>\n'


def _variant_notes(variants: list[flow.Variant]) -> list[str]:
    """Describe how the other observed paths differed from the one drawn."""
    notes: list[str] = []
    for variant in variants[1:]:
        if not variant.differs:
            continue
        tests = "test" if variant.count == 1 else "tests"
        parts = []
        if variant.added:
            parts.append("also called " + ", ".join(f"`{n}`" for n in variant.added))
        if variant.missing:
            parts.append("skipped " + ", ".join(f"`{n}`" for n in variant.missing))
        notes.append(f"- {variant.count} {tests} {' and '.join(parts)}")
    return notes


def _provenance(scenario: Scenario, trace: dict[str, Any]) -> str:
    """The 'inspect the code that generated this' block."""
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
    lines.extend(_fence(path) for path in scenario.source_files())
    return "\n".join(lines)


def _hook_table(graph: analysis.HookGraph, base_url: str) -> str:
    rows = ["| Hook | Calls | Semantics | Implementations |", "| --- | --: | --- | --: |"]
    labels = {
        "plain": "",
        "historic": "historic",
        "firstresult": "firstresult",
        "both": "historic, firstresult",
    }
    for name in sorted(graph.hooks):
        hook = graph.hooks[name]
        url = doclinks.hook_url(name, base_url)
        rows.append(
            f"| [`{name}`]({url}) | {hook.call_count} | "
            f"{labels[hook.semantics]} | {len(hook.plugins)} |"
        )
    return "\n".join(rows)


def scenario_page(scenario: Scenario, trace: dict[str, Any], verify_links: bool = True) -> str:
    base_url = doclinks.resolve_base_url(trace["environment"]["pytest"], verify=verify_links)
    hookspecs = trace["hookspecs"]
    parts = [f"# {scenario.title}\n", f"{scenario.summary}\n", f"{scenario.description}\n"]
    parts.append(_provenance(scenario, trace))

    totals = {name: hook.call_count for name, hook in analysis.full_graph(trace).hooks.items()}

    parts.append("## The whole run\n")
    parts.append(
        "Phases left to right, steps top to bottom. Colour says which phase a "
        "hook belongs to; how dark a step is says how often it was called. "
        "Each phase below expands one of these columns in full.\n"
    )
    parts.append(_overview(trace, base_url, totals))

    for phase in analysis.PHASES:
        variants = flow.phase_variants(analysis.find_subtrees(trace["calls"], phase.anchors))
        if not variants:
            continue
        parts.append(f"## {phase.title}\n")
        parts.append(f"{phase.description}\n")
        parts.append(_diagram(variants[0].flow, hookspecs, base_url, phase.key, totals))

        total = sum(variant.count for variant in variants)
        if total > 1:
            parts.append(f"*The path {variants[0].count} of {total} took.*\n")
        notes = _variant_notes(variants)
        if notes:
            parts.append("**The others differed:**\n")
            parts.extend(notes)
            parts.append("")

    full = analysis.full_graph(trace)
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
                "This is the practical reason some behaviour can only come from "
                "a plugin, never from a `conftest.py`.\n"
            )
            parts.extend(f"- [`{name}`]({doclinks.hook_url(name, base_url)})" for name in blind)
            parts.append("")

    parts.append("## Every hook observed\n")
    parts.append(_hook_table(full, base_url) + "\n")
    return "\n".join(parts)


def index_page(captured: list[tuple[Scenario, dict[str, Any]]]) -> str:
    environment = captured[0][1]["environment"] if captured else {}
    parts = [
        "# pytest hook atlas\n",
        "A visual reference for the **order and nesting of pytest's hooks** - "
        "captured from real pytest runs, not transcribed from prose.\n",
        "Every diagram is traced with pluggy's hook monitoring, so it shows "
        "what pytest actually did: the sequence, what ran inside what, and "
        "which plugin supplied each implementation.\n",
        "## Scenarios\n",
        "The flow genuinely changes with your project layout. Each scenario "
        "links back to the code it was traced from.\n",
        "| Scenario | What it shows | Hook calls |",
        "| --- | --- | --: |",
    ]
    parts.extend(
        f"| [{scenario.title}](scenarios/{scenario.id}.md) "
        f"| {scenario.summary} | {trace['stats']['total_calls']} |"
        for scenario, trace in captured
    )
    parts.append("\n## How to read the diagrams\n")
    parts.append(LEGEND)
    if environment:
        parts.append("## Captured with\n")
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
    (docs_dir / "scenarios").mkdir(parents=True, exist_ok=True)
    (docs_dir / "assets").mkdir(parents=True, exist_ok=True)
    (docs_dir / "assets" / "atlas.css").write_text(css.stylesheet())

    captured: list[tuple[Scenario, dict[str, Any]]] = []
    for scenario in discover(repo_root / "scenarios"):
        trace_path = traces_dir / f"{scenario.id}.json"
        if trace_path.exists():
            captured.append((scenario, analysis.load_trace(trace_path)))

    written = []
    for scenario, trace in captured:
        page = docs_dir / "scenarios" / f"{scenario.id}.md"
        page.write_text(scenario_page(scenario, trace, verify_links))
        written.append(page)

    index = docs_dir / "index.md"
    index.write_text(index_page(captured))
    written.append(index)
    return written
