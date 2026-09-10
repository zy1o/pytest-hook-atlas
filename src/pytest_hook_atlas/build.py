"""Generate the MkDocs source tree from captured traces.

Everything under ``docs/`` and ``mkdocs.yml`` itself is generated; the
committed inputs are ``scenarios/`` (the code), ``data/traces/`` (the captures)
and ``mkdocs.base.yml`` (the site template).

**Every captured version gets a URL.** A group's canonical page lives at its
first version, and every other version in the group gets a small alias page
pointing there. That matters because backfilling *older* pytest releases can
extend a group backwards and move its first version - naming is stable when a
scenario is added, but not when history is prepended. Aliases mean no URL ever
stops working either way.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packaging.version import Version

from . import analysis, doclinks, flow, grouping
from .grouping import Group
from .render import css, dot
from .scenarios import Scenario, discover

OUTLINE_DEPTH = 2

#: Mirrors python-markdown's default heading slugifier, which is what turns a
#: "## Collection" heading into id="collection". Derived from the same title
#: that generates the heading, so the two cannot drift apart.
_SLUG_STRIP = re.compile(r"[^\w\s-]")
_SLUG_SPACES = re.compile(r"[-\s]+")


def heading_anchor(title: str) -> str:
    return _SLUG_SPACES.sub("-", _SLUG_STRIP.sub("", title).strip().lower())


#: Render the last N pytest majors. Retention governs rendering only - every
#: trace stays committed, so raising this and rebuilding brings them back.
RETAINED_MAJORS = 4


@dataclass
class ScenarioBuild:
    """Everything needed to render one scenario's pages."""

    scenario: Scenario
    traces: dict[str, dict[str, Any]]
    groups: list[Group] = field(default_factory=list)

    @property
    def rendered(self) -> list[Group]:
        return grouping.retain(self.groups, RETAINED_MAJORS)

    @property
    def latest(self) -> Group | None:
        return self.rendered[-1] if self.rendered else None

    def group_of(self, version: str) -> Group | None:
        for group in self.groups:
            if version in group.versions:
                return group
        return None


def collect(repo_root: Path, traces_dir: Path) -> list[ScenarioBuild]:
    """Load every trace, fingerprint it, and group the versions per scenario."""
    builds = []
    for scenario in discover(repo_root / "scenarios"):
        traces = {}
        for version_dir in sorted(traces_dir.iterdir(), key=lambda p: p.name):
            trace_path = version_dir / f"{scenario.id}.json"
            if trace_path.exists():
                traces[version_dir.name] = analysis.load_trace(trace_path)
        if not traces:
            continue
        fingerprints = {v: grouping.fingerprint(t) for v, t in traces.items()}
        builds.append(ScenarioBuild(scenario, traces, grouping.group_versions(fingerprints)))
    return builds


def _diagram(
    nodes: list[flow.FlowNode],
    hookspecs: dict[str, Any],
    base_url: str,
    phase: str,
    totals: dict[str, int],
) -> str:
    """Inline the SVG so its links stay clickable and CSS can theme it."""
    if not nodes:
        return ""
    svg = dot.render_inline_svg(nodes, hookspecs, base_url, phase, totals)
    return f'<div class="ha-diagram">\n{svg}\n</div>\n'


def _overview(trace: dict[str, Any], base_url: str, totals: dict[str, int]) -> str:
    """The whole session as columns: phases left to right, steps top to bottom.

    Depth-limited on purpose. At full depth the collection column alone runs to
    29 nested steps and the page is about two and a half screens. That
    collection dwarfs the other columns is not imbalance to fix - it is where
    pytest's complexity is, and the picture should say so.
    """
    columns = []
    links = {}
    for phase in analysis.PHASES:
        variants = flow.phase_variants(analysis.find_subtrees(trace["calls"], phase.anchors))
        if variants:
            columns.append((phase.key, phase.title, flow.prune(variants[0].flow, OUTLINE_DEPTH)))
            links[phase.key] = f"#{heading_anchor(phase.title)}"
    if not columns:
        return ""
    svg = dot.to_inline_svg(
        dot.build_columns(columns, trace["hookspecs"], base_url, totals, anchors=links)
    )
    return f'<div class="ha-diagram">\n{svg}\n</div>\n'


def _version_picker(build: ScenarioBuild, current: str) -> str:
    """A dropdown over every captured version, not just the group keys.

    Readers think in pytest versions; the site is organised by distinct flows.
    Picking any version lands on the group covering it.
    """
    options = []
    for version in sorted(build.traces, key=Version, reverse=True):
        group = build.group_of(version)
        if group is None or group not in build.rendered:
            continue
        selected = " selected" if version == current else ""
        options.append(f'<option value="../{version}/"{selected}>pytest {version}</option>')
    if not options:
        return ""
    return (
        '<div class="ha-version-picker">\n'
        '  <label for="ha-version">Showing</label>\n'
        '  <select id="ha-version" onchange="location.href=this.value">\n    '
        + "\n    ".join(options)
        + "\n  </select>\n</div>\n"
    )


def _variant_notes(variants: list[flow.Variant]) -> list[str]:
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


def _provenance(scenario: Scenario, trace: dict[str, Any], group: Group) -> str:
    environment = trace["environment"]
    invocation = " ".join(["pytest", *scenario.args])
    covered = f"{len(group)} releases" if len(group) > 1 else "1 release"
    lines = [
        "## How this was produced\n",
        f"- **Source:** [`scenarios/{scenario.id}/`]({scenario.source_url})"
        " - the project this diagram was traced from",
        f"- **Invocation:** `{invocation}`",
        f"- **Traced against:** pytest {group.newest}, pluggy "
        f"{environment['pluggy']}, Python {environment['python']}",
        f"- **Covers:** {covered} - {group.label}, which produced an identical flow",
        f"- **Observed:** {trace['stats']['total_calls']} hook calls, "
        f"{trace['stats']['unique_hooks']} distinct hooks\n",
    ]
    names = ", ".join(f"`{path.name}`" for path in scenario.source_files())
    if names:
        lines.append(
            f"The project is {names}. Browse it in the repository rather than "
            "inline here - scenarios grow directory trees, and GitHub renders "
            "them better than a collapsed block can.\n"
        )
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


def group_page(build: ScenarioBuild, group: Group, verify_links: bool = True) -> str:
    """The canonical page for one distinct flow."""
    scenario = build.scenario
    trace = build.traces[group.newest]
    # a group's links point at the newest pytest version it covers
    base_url = doclinks.resolve_base_url(group.newest, verify=verify_links)
    hookspecs = trace["hookspecs"]
    totals = {n: h.call_count for n, h in analysis.full_graph(trace).hooks.items()}

    parts = [
        f"# {scenario.title}\n",
        _version_picker(build, group.newest),
        f"**{group.label}** - {scenario.summary}\n",
    ]
    if len(group) > 1:
        parts.append(
            f"These {len(group)} releases produced an identical flow, so they "
            "share one page. *Identical as far as this scenario can measure* - "
            "a scenario exercising more hooks may tell them apart.\n"
        )
    parts.append(f"{scenario.description}\n")
    parts.append(_provenance(scenario, trace, group))

    parts.append("## The whole run\n")
    parts.append(
        "Phases left to right, steps top to bottom. Colour says which phase a "
        "hook belongs to; how dark a step is says how often it was called. "
        "**Click a column heading** to jump to that phase in full detail, or "
        "any hook to open its pytest documentation. "
        "[Why it looks like this](../../design-notes.md)\n"
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
            parts.extend(f"- [`{name}`]({doclinks.hook_url(name, base_url)})" for name in blind)
            parts.append("")

    parts.append("## Every hook observed\n")
    parts.append(_hook_table(full, base_url) + "\n")
    return "\n".join(parts)


def alias_page(scenario: Scenario, version: str, group: Group) -> str:
    """A version inside a group, pointing at the group's canonical page.

    Exists so that every captured version has a URL that keeps working even
    when a later backfill extends the group backwards and moves its key.
    """
    return (
        f'<meta http-equiv="refresh" content="0; url=../{group.key}/">\n\n'
        f"# pytest {version}\n\n"
        f"The hook flow for pytest {version} is unchanged across "
        f"**{group.label}**, so it is documented on one page.\n\n"
        f"[Continue to {group.label}]({group.key}.md)\n"
    )


def latest_page(scenario: Scenario, group: Group) -> str:
    return (
        f'<meta http-equiv="refresh" content="0; url=../{group.key}/">\n\n'
        f"# {scenario.title}, latest pytest\n\n"
        f"The newest captured flow is **{group.label}**.\n\n"
        f"[Continue to {group.label}]({group.key}.md)\n"
    )


def scenario_index(build: ScenarioBuild) -> str:
    scenario = build.scenario
    parts = [
        f"# {scenario.title}\n",
        f"{scenario.summary}\n",
        f"{scenario.description}\n",
        "[**Latest pytest**](latest.md) - or pick a flow below.\n",
        "## Distinct flows\n",
        f"{len(build.traces)} captured releases produce {len(build.groups)} distinct flows.\n",
        "| Flow | Releases | |",
        "| --- | --: | --- |",
    ]
    for group in reversed(build.rendered):
        parts.append(f"| [{group.label}]({group.key}.md) | {len(group)} | |")
    return "\n".join(parts)


def versions_page(builds: list[ScenarioBuild]) -> str:
    parts = [
        "# Every captured release\n",
        "Which flow each pytest release belongs to, per scenario. Releases "
        "sharing a flow share a page.\n",
        "| pytest | " + " | ".join(b.scenario.title for b in builds) + " |",
        "| --- | " + " | ".join("---" for _ in builds) + " |",
    ]
    versions = sorted({v for b in builds for v in b.traces}, key=Version, reverse=True)
    for version in versions:
        cells = []
        for build in builds:
            group = build.group_of(version)
            if group is None or group not in build.rendered:
                cells.append("-")
            else:
                cells.append(f"[{group.label}](scenarios/{build.scenario.id}/{group.key}.md)")
        parts.append(f"| **{version}** | " + " | ".join(cells) + " |")
    return "\n".join(parts)


def changes_page(builds: list[ScenarioBuild]) -> str:
    parts = [
        "# What changed between releases\n",
        "Every point where a captured flow changed. A boundary appears only "
        "because something actually moved - these are the same boundaries that "
        "decide where one page ends and the next begins.\n",
        "Note that a reordering leaves pytest's declared hookspec untouched, so "
        "it cannot be found by reading `hookspec.py`. Only running pytest shows "
        "it.\n",
    ]
    for build in builds:
        parts.append(f"## {build.scenario.title}\n")
        groups = build.rendered
        if len(groups) < 2:
            parts.append("No changes observed across the captured releases.\n")
            continue
        for older, newer in zip(groups, groups[1:], strict=False):
            before = set(analysis.full_graph(build.traces[older.newest]).hooks)
            after = set(analysis.full_graph(build.traces[newer.newest]).hooks)
            parts.append(f"### {older.newest} to {newer.key}\n")
            added, removed = sorted(after - before), sorted(before - after)
            if added:
                parts.append("- **New hooks:** " + ", ".join(f"`{n}`" for n in added))
            if removed:
                parts.append("- **Gone:** " + ", ".join(f"`{n}`" for n in removed))
            if not added and not removed:
                parts.append(
                    "- Same set of hooks, different order or nesting - the kind "
                    "of change only a real run reveals."
                )
            directory = f"scenarios/{build.scenario.id}"
            parts.append(
                f"- [Before]({directory}/{older.key}.md) / [After]({directory}/{newer.key}.md)\n"
            )
    return "\n".join(parts)


def design_notes() -> str:
    return DESIGN_NOTES


def site_index(builds: list[ScenarioBuild]) -> str:
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
        "| Scenario | What it shows | Releases | Distinct flows |",
        "| --- | --- | --: | --: |",
    ]
    for build in builds:
        parts.append(
            f"| [{build.scenario.title}](scenarios/{build.scenario.id}/index.md) "
            f"| {build.scenario.summary} | {len(build.traces)} | {len(build.groups)} |"
        )
    parts.append(
        "\n[Every captured release](versions.md) - "
        "[What changed between releases](changes.md) - "
        "[Why the diagrams look like this](design-notes.md)\n"
    )
    return "\n".join(parts)


DESIGN_NOTES = """# Why the diagrams look like this

## Order, not just containment

An earlier version of this site drew only *containment* - an arrow meant
"called inside", never "then". `pytest_runtest_protocol` fanned out into eight
unordered boxes, and the thing people actually get wrong stayed invisible:
setup, call and teardown are each followed by their own `makereport` and
`logreport` pair. Three reports per test, not one.

Arrows now mean **what happened next**, in the order the trace recorded.
Nesting is drawn as a box inside a box.

## Colour means phase; darkness means frequency

Two channels, kept separate. Hue tells you which part of the run a hook belongs
to. How dark a step is tells you how often it was called - on a logarithmic
scale, because counts run from 1 to about 80 in a single session and a linear
ramp would flatten everything below ten into the palest shade.

Nothing else uses colour. In particular, differences between pytest versions
deliberately do not get one: a hook appearing or disappearing is something you
can find with ctrl-F, and a hook *moving* is surfaced by
[grouping](changes.md) instead, which is where it belongs.

## The palette was measured, not chosen

The four phase colours were picked by simulating dichromatic vision and
maximising the worst-case separation across normal, protanopia, deuteranopia
and tritanopia.

This was not a formality. The obvious palette - the Google-ish blue, green,
amber and purple that most tools reach for - put two of its four hues at a
colour difference of **3.9** under deuteranopia. That is effectively
indistinguishable, and deuteranopia affects roughly 1 in 12 men. Those readers
would have seen the first and last phases as one colour. The palette in use
scores **48.5** on the same measure.

Every colour carrying text or a border is also pushed toward or away from the
page background until it clears the WCAG AA contrast ratio, separately for the
light and dark themes. Raw hues failed badly here: one scored 1.6:1 as a title
on white, another 1.3:1 on the dark background.

There is deliberately **no green and no alarm-red**. The phases are categories,
not statuses, and a traffic-light reading would imply an ordering - "collection
passed, the run-test phase is a warning" - that does not exist.

Finally, colour is **redundant** throughout. Every column also carries a title,
a border and a fixed position, and every hook's semantics are written out in
words beneath its name rather than encoded in a shape. A reader who cannot
distinguish the hues loses an accelerator, never information.

## Overview first, detail below

The overview is depth-limited so the whole session fits on one screen. At full
depth the collection column alone runs to 29 nested steps and the page is about
two and a half screens tall.

That collection dwarfs the other columns is not a flaw in the layout. Most of
pytest's machinery is in startup and collection; running a test is largely just
calling a Python function, and the phases after it are mostly reporting. The
picture should say that, so it does.

## Hooks that are not drawn faithfully

Two hooks are excluded from the fingerprint that decides when versions are
grouped, though they are still drawn:

`pytest_plugin_registered` fires once per registered plugin, so its count
tracks how many internal plugins a pytest release happens to ship. Two releases
can differ by that alone, which is not a change worth a separate page.

`pytest_warning_recorded` is deferred. pytest wraps five hooks in
`warnings.catch_warnings(record=True)` and replays the whole batch from a
`finally` block once the wrapped phase ends. So its position in the diagram
marks a phase boundary rather than the moment a warning was raised, and its
count depends on whatever happened to warn.
"""


NAV_INDENT = "  "


def _nav(builds: list[ScenarioBuild]) -> str:
    lines = ["nav:", f"{NAV_INDENT}- Home: index.md"]
    for build in builds:
        scenario_id = build.scenario.id
        lines.append(f"{NAV_INDENT}- {build.scenario.title}:")
        lines.append(f"{NAV_INDENT * 2}- Overview: scenarios/{scenario_id}/index.md")
        for group in reversed(build.rendered):
            lines.append(f"{NAV_INDENT * 2}- {group.label}: scenarios/{scenario_id}/{group.key}.md")
    lines.append(f"{NAV_INDENT}- Every release: versions.md")
    lines.append(f"{NAV_INDENT}- What changed: changes.md")
    lines.append(f"{NAV_INDENT}- Design notes: design-notes.md")
    # alias and latest pages are intentionally absent from the nav
    lines.append("not_in_nav: |")
    lines.append(f"{NAV_INDENT}/scenarios/*/latest.md")
    for build in builds:
        keys = {group.key for group in build.rendered}
        for version in build.traces:
            if version not in keys:
                lines.append(f"{NAV_INDENT}/scenarios/{build.scenario.id}/{version}.md")
    return "\n".join(lines) + "\n"


def build(
    repo_root: Path, docs_dir: Path, traces_dir: Path, verify_links: bool = True
) -> list[Path]:
    """Render every scenario's groups into ``docs_dir``. Returns pages written."""
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    (docs_dir / "assets").mkdir(parents=True, exist_ok=True)
    (docs_dir / "assets" / "atlas.css").write_text(css.stylesheet())

    builds = collect(repo_root, traces_dir)
    written: list[Path] = []

    for item in builds:
        directory = docs_dir / "scenarios" / item.scenario.id
        directory.mkdir(parents=True, exist_ok=True)

        (directory / "index.md").write_text(scenario_index(item))
        written.append(directory / "index.md")

        for group in item.rendered:
            page = directory / f"{group.key}.md"
            page.write_text(group_page(item, group, verify_links))
            written.append(page)

            for version in group.versions:
                if version == group.key:
                    continue
                alias = directory / f"{version}.md"
                alias.write_text(alias_page(item.scenario, version, group))
                written.append(alias)

        if item.latest:
            latest = directory / "latest.md"
            latest.write_text(latest_page(item.scenario, item.latest))
            written.append(latest)

    for name, content in (
        ("index.md", site_index(builds)),
        ("versions.md", versions_page(builds)),
        ("changes.md", changes_page(builds)),
        ("design-notes.md", design_notes()),
    ):
        (docs_dir / name).write_text(content)
        written.append(docs_dir / name)

    template = (repo_root / "mkdocs.base.yml").read_text()
    (repo_root / "mkdocs.yml").write_text(template.rstrip() + "\n\n" + _nav(builds))
    return written
