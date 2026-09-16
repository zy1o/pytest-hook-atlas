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

from hook_atlas import flow, grouping, implementers
from hook_atlas.grouping import Group
from hook_atlas.render import css, dot
from packaging.version import Version

from . import analysis, doclinks
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
#: How many pytest majors get pages. Every trace stays committed regardless -
#: this governs what is *rendered*, so widening it and rebuilding brings older
#: releases back with no re-capture. Four currently means 6.x through 9.x, which
#: is everything; the day pytest 10 ships, 6.x stops rendering unless this is
#: raised. Zero renders every group.
RETAINED_MAJORS = 4


def _natural(name: str) -> tuple:
    """Sort key treating digit runs as numbers: gw2 before gw10."""
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part) for part in re.split(r"(\d+)", name) if part
    )


@dataclass
class ScenarioBuild:
    """Everything needed to render one scenario's pages."""

    scenario: Scenario
    #: version -> process -> trace. An ordinary scenario has the single
    #: process "main"; a distributed one has "controller" and a worker each.
    traces: dict[str, dict[str, dict[str, Any]]]
    groups: list[Group] = field(default_factory=list)
    #: Majors to render. Zero means all of them. See :data:`RETAINED_MAJORS`.
    majors: int = RETAINED_MAJORS

    def processes(self, version: str) -> list[str]:
        """Processes captured for a version, controller first then workers.

        Workers sort naturally, so `gw2` comes before `gw10` rather than after
        it - which is what a plain sort does, and reads as a mistake on any run
        with ten or more workers.
        """
        return sorted(
            self.traces.get(version, {}),
            key=lambda name: (name != "controller", _natural(name)),
        )

    def trace(self, version: str, process: str | None = None) -> dict[str, Any]:
        """One process's trace, defaulting to the one that ran the session."""
        captured = self.traces[version]
        return captured[process] if process else captured[self.processes(version)[0]]

    def per_version(self, process: str | None = None) -> dict[str, dict[str, Any]]:
        """One trace per version, for reconciling implementers across a range.

        Defaults to whichever process ran the session, so callers that predate
        distributed scenarios - and every non-distributed scenario - keep seeing
        exactly one trace per version.
        """
        found = {}
        for version, captured in self.traces.items():
            name = process or self.processes(version)[0]
            if name in captured:
                found[version] = captured[name]
        return found

    def captures(self) -> list[tuple[str, str, dict[str, Any]]]:
        """Every ``(version, process, trace)`` this scenario recorded."""
        return [
            (version, process, trace)
            for version, captured in sorted(self.traces.items())
            for process, trace in sorted(captured.items())
        ]

    @property
    def rendered(self) -> list[Group]:
        if not self.majors:
            return self.groups
        return grouping.retain(self.groups, self.majors)

    @property
    def latest(self) -> Group | None:
        return self.rendered[-1] if self.rendered else None

    def group_of(self, version: str) -> Group | None:
        for group in self.groups:
            if version in group.versions:
                return group
        return None


def _process_of(trace_path: Path, scenario_id: str) -> str:
    """``xdist.gw0.json`` -> ``gw0``; ``baseline.json`` -> ``main``."""
    stem = trace_path.name[: -len(trace_path.suffix)]
    return stem[len(scenario_id) :].lstrip(".") or "main"


#: Hooks kept out of the fingerprint. pytest_plugin_registered fires whenever
#: anything registers, and pytest_warning_recorded is replayed in a batch whose
#: position marks a phase boundary rather than where a warning arose - neither
#: is a property of the pytest release being documented.
BOOKKEEPING_HOOKS = frozenset({"pytest_plugin_registered", "pytest_warning_recorded"})

#: What counts as pytest implementing a hook itself, for the "hide internal
#: plugins" toggle. pytest keeps its own under `_pytest`.
INTERNAL_PREFIXES = implementers.internal_prefixes("pytest")


def _fingerprint(trace: dict[str, Any]) -> str:
    """A trace's flow identity, as pytest defines it."""
    return grouping.fingerprint(trace, analysis.PHASES, BOOKKEEPING_HOOKS)


def _combined_fingerprint(captured: dict[str, dict[str, Any]]) -> str:
    """One fingerprint for a version across all its processes.

    Workers are compared as an unordered set. Which worker picks up which chunk
    of a run is a race, so the same two flows appear as gw0/gw1 in one capture
    and gw1/gw0 in the next - keyed by name that made almost every pytest
    release its own group, 18 of 29, for a difference that is only a label.
    """
    primary = [name for name in captured if name in ("main", "controller")]
    workers = sorted(set(captured) - set(primary))
    lead = "+".join(_fingerprint(captured[name]) for name in sorted(primary))
    rest = sorted(_fingerprint(captured[name]) for name in workers)
    return "+".join([lead, *rest])


def collect(
    repo_root: Path, traces_dir: Path, majors: int = RETAINED_MAJORS
) -> list[ScenarioBuild]:
    """Load every trace, fingerprint it, and group the versions per scenario.

    A distributed scenario contributes several traces per version. Versions are
    grouped on the fingerprints of *all* its processes combined, so a change in
    any one of them starts a new group - a worker's flow changing matters as
    much as the controller's.
    """
    builds = []
    for scenario in discover(repo_root / "scenarios"):
        traces: dict[str, dict[str, dict[str, Any]]] = {}
        for version_dir in sorted(traces_dir.iterdir(), key=lambda p: p.name):
            found = sorted(version_dir.glob(f"{scenario.id}.json")) + sorted(
                version_dir.glob(f"{scenario.id}.*.json")
            )
            for trace_path in found:
                process = _process_of(trace_path, scenario.id)
                traces.setdefault(version_dir.name, {})[process] = analysis.load_trace(trace_path)
        if not traces:
            continue
        fingerprints = {
            version: _combined_fingerprint(captured) for version, captured in traces.items()
        }
        builds.append(
            ScenarioBuild(
                scenario,
                traces,
                grouping.group_versions(fingerprints, application="pytest"),
                majors=majors,
            )
        )
    return builds


def _diagram(
    nodes: list[flow.FlowNode],
    hookspecs: dict[str, Any],
    links: doclinks.DocLinks,
    phase: str,
    totals: dict[str, int],
) -> str:
    """Inline the SVG so its links stay clickable and CSS can theme it."""
    if not nodes:
        return ""
    drawn = flow.fold_repetitive(nodes)
    svg = dot.render_inline_svg(drawn, hookspecs, links, phase, totals)
    diagram = f'<div class="ha-diagram">\n{svg}\n</div>\n'
    if _has_summary(drawn):
        diagram += (
            "*A dashed box stands in for a long stretch that only reorders the "
            "few hooks it names - under xdist, results arriving from workers in "
            "whatever order they happened to finish. Every hook is still listed "
            "below.*\n"
        )
    return diagram


def _has_summary(nodes: list[flow.FlowNode]) -> bool:
    return any(node.is_summary or _has_summary(node.children) for node in nodes)


def _overview(
    trace: dict[str, Any],
    links: doclinks.DocLinks,
    totals: dict[str, int],
    anchors: dict[str, str] | None = None,
) -> str:
    """The whole session as columns: phases left to right, steps top to bottom.

    Depth-limited on purpose. At full depth the collection column alone runs to
    29 nested steps and the page is about two and a half screens. That
    collection dwarfs the other columns is not imbalance to fix - it is where
    pytest's complexity is, and the picture should say so.
    """
    columns = []
    jumps = {}
    for phase in analysis.PHASES:
        variants = flow.phase_variants(analysis.phase_subtrees(trace, phase))
        if variants:
            # fold first: pruning depth does nothing about ninety siblings
            outline = flow.prune(flow.fold_repetitive(variants[0].flow), OUTLINE_DEPTH)
            columns.append((phase.key, phase.title, outline))
            jumps[phase.key] = (anchors or {}).get(phase.key, f"#{heading_anchor(phase.title)}")
    if not columns:
        return ""
    svg = dot.to_inline_svg(
        dot.build_columns(columns, trace["hookspecs"], links, totals, anchors=jumps)
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
    # from the trace, not rebuilt from scenario.args: the trace is what a
    # capture of someone else's project will have, and it is the record of what
    # actually ran rather than what we meant to run
    invocation = " ".join(["pytest", *invocation_of(trace)])
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


SEMANTIC_LABELS = {
    "plain": "",
    "historic": "historic",
    "firstresult": "firstresult",
    "both": "historic, firstresult",
}


def _hook_table(
    graph: analysis.HookGraph,
    links: doclinks.DocLinks,
    implemented: dict[str, implementers.HookImplementers],
    hookspecs: dict[str, Any],
) -> str:
    """Every hook observed, with the plugins behind it in call order.

    pytest implements most of itself as plugins, so this column is mostly
    pytest's own internals - which is the point. Names are wrapped in code
    spans, which is not only style: one plugin registers as ``<anonymous>``,
    and unescaped that is swallowed as an HTML tag.
    """
    rows = [
        "| Hook | Calls | Semantics | Implemented by, in call order |",
        "| --- | --: | --- | --- |",
    ]
    for name in sorted(graph.hooks):
        hook = graph.hooks[name]
        url = links.url_for(name, hookspecs.get(name, {}).get("declared_in"))
        label = f"[`{name}`]({url})" if url else f"`{name}`"
        info = implemented.get(name)
        if info and info.current:
            listed = "<br>".join(
                f'<span class="ha-impl ha-{"internal" if item.internal else "external"}">'
                f"`{item.label}`"
                + (f' <span class="ha-flags">{item.annotation}</span>' if item.annotation else "")
                + "</span>"
                for item in info.current
            )
        else:
            listed = "<br>".join(f"`{plugin}`" for plugin in hook.plugins) or "-"
        if info and not info.stable:
            listed += f"<br>[^{name}]"
        rows.append(
            f"| {label} | {hook.call_count} | {SEMANTIC_LABELS[hook.semantics]} | {listed} |"
        )
    return "\n".join(rows)


def _implementer_changes(
    implemented: dict[str, implementers.HookImplementers], group: Group
) -> list[str]:
    """Footnotes for hooks whose implementers changed inside this range.

    Written as deltas rather than full re-listings. ``pytest_configure`` has
    eighteen implementers and changed five times across one range; printing the
    whole list five times is unreadable, and what changed is both short and the
    thing worth knowing.
    """
    varying = [info for info in implemented.values() if not info.stable]
    if not varying:
        return []

    lines = [
        f"\n*{len(varying)} of these changed implementer somewhere in "
        f"{group.label} without changing the flow - pytest moves "
        "implementations between its own plugins. The table shows the newest; "
        "what changed along the way is below.*\n",
    ]
    for info in sorted(varying, key=lambda item: item.hook):
        changes = []
        for version, gained, lost in info.deltas():
            bits = []
            if gained:
                bits.append("gained " + ", ".join(f"`{p}`" for p in gained))
            if lost:
                bits.append("lost " + ", ".join(f"`{p}`" for p in lost))
            changes.append(f"**{version}** {' and '.join(bits) or 'reordered'}")
        lines.append(f"[^{info.hook}]: " + "; ".join(changes) + "\n")
    return lines


PROCESS_TITLES = {
    "controller": "The controller",
    "main": "",
}


def process_title(process: str) -> str:
    return PROCESS_TITLES.get(process) or f"Worker {process}"


def _phase_heading(phase: analysis.Phase, process: str, distributed: bool) -> str:
    """Phase headings must be unique per process, or their anchors collide.

    The overview columns link to these headings, so two processes both headed
    "Collection" would send one of them to the wrong diagram.
    """
    if not distributed:
        return phase.title
    label = "controller" if process == "controller" else process
    return f"{phase.title} ({label})"


#: Flags this project adds to instrument the run. They are not part of the
#: command being documented, so they are stripped before it is shown.
INSTRUMENTATION = ("hook_atlas_tracer", "no:cacheprovider")


def invocation_of(trace: dict[str, Any]) -> list[str]:
    """The pytest command this process ran, without our own instrumentation.

    Only ``-p <ours>`` pairs are dropped. A project loading its own plugin with
    ``-p`` is part of the command being documented and must survive.
    """
    argv = trace.get("scenario", {}).get("argv") or []
    kept: list[str] = []
    index = 0
    while index < len(argv):
        if (
            argv[index] == "-p"
            and argv[index + 1 : index + 2]
            and argv[index + 1] in INSTRUMENTATION
        ):
            index += 2
            continue
        kept.append(argv[index])
        index += 1
    return kept


def _command(trace: dict[str, Any], process: str) -> str:
    """What this process was launched with.

    Worth printing per process rather than once per page: the flow depends on
    the command, and under xdist the workers do not have one. They are started
    over execnet and handed a config, which is why their argv is empty - a
    genuine fact about how distribution works, not a gap in the capture.
    """
    argv = invocation_of(trace)
    if argv:
        return f"**Command:** `{' '.join(['pytest', *argv])}`\n"
    return (
        "**Command:** none. xdist starts a worker over execnet and hands it a "
        "configuration, so it has no command line of its own.\n"
    )


def _process_section(
    build: ScenarioBuild,
    group: Group,
    process: str,
    links: doclinks.DocLinks,
    heading_level: str,
    shared: WorkerFlow | None = None,
) -> list[str]:
    """Overview, phases and hook table for one process."""
    scenario = build.scenario
    trace = build.trace(group.newest, process)
    hookspecs = trace["hookspecs"]
    totals = {n: h.call_count for n, h in analysis.full_graph(trace).hooks.items()}
    distributed = scenario.distributed
    parts: list[str] = []

    if distributed:
        total = len(build.processes(group.newest)) - 1
        title = worker_heading(shared, total) if shared else process_title(process)
        parts.append(f"{heading_level} {title}\n")
        if shared:
            parts.append(worker_note(shared, total))
        parts.append(_command(trace, process))

    parts.append(
        "Phases left to right, steps top to bottom. Colour says which phase a "
        "hook belongs to; how dark a step is says how often it was called. "
        "**Click a column heading** to jump to that phase in full detail, or "
        "any hook to open its pytest documentation. "
        "[Why it looks like this](../../design-notes.md)\n"
    )
    anchors = {
        phase.key: f"#{heading_anchor(_phase_heading(phase, process, distributed))}"
        for phase in analysis.PHASES
    }
    parts.append(_overview(trace, links, totals, anchors))

    sub = heading_level + "#" if distributed else heading_level
    for phase in analysis.PHASES:
        variants = flow.phase_variants(analysis.phase_subtrees(trace, phase))
        if not variants:
            continue
        parts.append(f"{sub} {_phase_heading(phase, process, distributed)}\n")
        parts.append(f"{phase.description}\n")
        parts.append(_diagram(variants[0].flow, hookspecs, links, phase.key, totals))

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
            parts.append(f"{sub} Hooks a conftest cannot serve\n")
            parts.append(
                "This scenario's `conftest.py` implements **every** hook pytest "
                "declares. The hooks below still fired *without* it: the "
                "implementation was registered and never invoked, because the "
                "conftest had not been imported yet when the hook ran, or sits "
                "below the level the hook applies to.\n"
            )
            parts.extend(
                f"- [`{name}`]({links.url_for(name, '_pytest.hookspec')})" for name in blind
            )
            parts.append("")

    # unique per process, or two identical headings collide as anchors
    heading = (
        f"{sub} Every hook observed ({process})\n" if distributed else "## Every hook observed\n"
    )
    parts.append(heading)
    implemented = implementers.reconcile(
        build.per_version(process), group.versions, internal=INTERNAL_PREFIXES
    )
    # wrapped so the filter script can find this table specifically; markdown="1"
    # keeps the table inside it rendered as markdown
    parts.append('<div class="ha-hook-table" markdown="1">\n')
    parts.append(_hook_table(full, links, implemented, hookspecs) + "\n")
    parts.append("</div>\n")
    parts.extend(_implementer_changes(implemented, group))
    return parts


@dataclass
class WorkerFlow:
    """One distinct flow, and every worker that produced it."""

    #: worker names sharing this flow, in xdist's order
    workers: list[str]
    #: the worker actually drawn - the first, and the one anchors are keyed on
    drawn: str

    @property
    def shared(self) -> bool:
        return len(self.workers) > 1


def worker_flows(build: ScenarioBuild, version: str) -> list[WorkerFlow]:
    """Group a version's workers by the flow they produced.

    Workers are grouped rather than labelled because worker *names* are a race.
    Captured twice in a row under a splitting scheduler, gw0 and gw1 swap: the
    split is reproducible, which worker draws which half is not. Keyed by name,
    a page would report a difference between two workers that is only who won.

    Every distinct flow is drawn in full, however many there are. A real suite
    across a dozen workers may well produce a dozen different flows, and that is
    the thing worth seeing rather than something to summarise away.
    """
    flows: dict[str, WorkerFlow] = {}
    for worker in build.processes(version):
        if worker == "controller":
            continue
        key = _fingerprint(build.trace(version, worker))
        if key in flows:
            flows[key].workers.append(worker)
        else:
            flows[key] = WorkerFlow(workers=[worker], drawn=worker)
    return list(flows.values())


def worker_note(shared: WorkerFlow, total: int) -> str:
    """Say which workers this flow covers, and which one is drawn."""
    count = len(shared.workers)
    if count == total:
        who = "Both workers" if total == 2 else f"All {total} workers"
        return f"*{who} produced this flow. `{shared.drawn}` is drawn.*\n"
    if count == 1:
        return f"*Only `{shared.drawn}` produced this flow, of {total} workers.*\n"
    return (
        f"*{count} of the {total} workers produced this flow - "
        f"{', '.join(shared.workers)}. `{shared.drawn}` is drawn.*\n"
    )


def worker_heading(shared: WorkerFlow, total: int) -> str:
    """Name a worker section by which workers it covers."""
    if len(shared.workers) == total:
        return "Every worker" if total > 1 else f"Worker {shared.drawn}"
    if not shared.shared:
        return f"Worker {shared.drawn}"
    names = ", ".join(shared.workers[:-1]) + f" and {shared.workers[-1]}"
    return f"Workers {names}"


def group_page(build: ScenarioBuild, group: Group, verify_links: bool = True) -> str:
    """The canonical page for one distinct flow."""
    scenario = build.scenario
    # a group's links point at the newest pytest version it covers
    links = doclinks.links_for(doclinks.resolve_base_url(group.newest, verify=verify_links))
    processes = build.processes(group.newest)

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
    parts.append(_provenance(scenario, build.trace(group.newest), group))

    if not scenario.distributed:
        parts.append("## The whole run\n")
        parts.extend(_process_section(build, group, processes[0], links, "##"))
        return "\n".join(parts)

    parts.extend(_process_section(build, group, "controller", links, "##"))
    for shared in worker_flows(build, group.newest):
        parts.extend(_process_section(build, group, shared.drawn, links, "##", shared=shared))
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
            before = set(analysis.full_graph(build.trace(older.newest)).hooks)
            after = set(analysis.full_graph(build.trace(newer.newest)).hooks)
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
        "## Want this for your own project?\n",
        "These pages show pytest running scenarios chosen to be instructive. "
        "For *your* suite - your plugins, your `conftest.py`, your layout - "
        "use [hook-atlas](https://github.com/zy1o/hook-atlas), which traces and "
        "draws any [pluggy](https://pluggy.readthedocs.io/)-based application "
        "and is what these diagrams are drawn with.\n",
        "```bash\n"
        "pip install hook-atlas\n"
        "hook-atlas trace -- pytest -q tests/\n"
        "hook-atlas draw          # then open hook-flow.html\n"
        "```\n",
        "It works on anything built on pluggy, not only pytest - tox and datasette included.\n",
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
        "[Why the diagrams look like this](design-notes.md) - "
        "[Changelog](changelog.md)\n"
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

## Why some stretches are folded away

A run has stretches where nothing new happens for a long time. The xdist
controller's run loop is over a hundred steps of `logstart`, `logreport`,
`report_from_serializable` and `logfinish` as results come back from workers -
in whatever order the workers happened to finish, which is why they do not
collapse into a repeat count the way identical consecutive steps do.

Drawn in full that is seven thousand pixels saying "reports came back". So one
cycle is drawn and the rest becomes a dashed box naming the hooks it stands
for. Folding happens **when drawing only**: it never enters the fingerprint
that decides which releases share a flow, and the hook table below each diagram
still lists everything that ran.

## Why the implementers are in that order

pluggy does not call a hook's implementations in registration order. Wrappers
run outermost, then anything marked `tryfirst`, then ordinary implementations,
then `trylast`. The hook table lists them in the order they actually run and
annotates the ones carrying a marker, so the sequence explains itself:

    _pytest.logging.LoggingPlugin   [wrapper]
    _pytest.capture.CaptureManager  [wrapper]
    _pytest.skipping                [tryfirst]
    conftest.py
    _pytest.runner
    _pytest.unraisableexception     [trylast]
    _pytest.threadexception         [trylast]

For a `firstresult` hook this decides which implementation wins: the first one
to return something other than `None` ends the call.

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
    lines.append(f"{NAV_INDENT}- Changelog: changelog.md")
    # alias and latest pages are intentionally absent from the nav
    lines.append("not_in_nav: |")
    lines.append(f"{NAV_INDENT}/scenarios/*/latest.md")
    for build in builds:
        keys = {group.key for group in build.rendered}
        for version in build.traces:
            if version not in keys:
                lines.append(f"{NAV_INDENT}/scenarios/{build.scenario.id}/{version}.md")
    return "\n".join(lines) + "\n"


FILTER_SCRIPT = """/* Hide pytest's own plugins in the hook table, leaving whatever
   the project under test contributes - a conftest, third-party plugins, your
   own. pytest implements nearly all of itself as plugins, so on most hooks the
   list is entirely internal and the few entries that are not get lost in it.

   Uses Material's document$ rather than DOMContentLoaded: navigation.instant
   swaps pages without a reload, so a one-shot listener would stop working after
   the first navigation.

   Progressive enhancement - with scripting off, everything is shown, which is
   the correct default. Generated by pytest_hook_atlas.build. */
document$.subscribe(function () {
  document.querySelectorAll(".ha-hook-table").forEach(function (container) {
    if (container.querySelector(".ha-filter")) return;

    const table = container.querySelector("table");
    if (!table) return;
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    // nothing outside pytest itself means nothing worth filtering
    if (!rows.some((row) => row.querySelector(".ha-external"))) return;

    const box = document.createElement("input");
    box.type = "checkbox";
    box.id = "ha-hide-internal";

    const label = document.createElement("label");
    label.className = "ha-filter";
    label.htmlFor = box.id;
    label.appendChild(box);
    label.appendChild(
      document.createTextNode(" Hide pytest's own plugins")
    );

    box.addEventListener("change", function () {
      container.classList.toggle("ha-hide-internal", box.checked);
      rows.forEach(function (row) {
        // a row with nothing left to show is noise, not information
        row.hidden = box.checked && !row.querySelector(".ha-external");
      });
    });

    container.insertBefore(label, container.firstChild);
  });
});
"""


def build(
    repo_root: Path,
    docs_dir: Path,
    traces_dir: Path,
    verify_links: bool = True,
    config_path: Path | None = None,
    majors: int = RETAINED_MAJORS,
) -> list[Path]:
    """Render every scenario's groups into ``docs_dir``. Returns pages written."""
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    (docs_dir / "assets").mkdir(parents=True, exist_ok=True)
    # the stylesheet carries one rule set per phase, so it must be told which
    (docs_dir / "assets" / "atlas.css").write_text(
        css.stylesheet([phase.key for phase in analysis.PHASES])
    )
    (docs_dir / "assets" / "filter.js").write_text(FILTER_SCRIPT)

    builds = collect(repo_root, traces_dir, majors)
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

    changelog = repo_root / "CHANGELOG.md"
    if changelog.exists():
        # copied rather than regenerated: the changelog is written by hand and
        # lives at the repository root, where GitHub shows it too
        (docs_dir / "changelog.md").write_text(changelog.read_text())
        written.append(docs_dir / "changelog.md")

    for name, content in (
        ("index.md", site_index(builds)),
        ("versions.md", versions_page(builds)),
        ("changes.md", changes_page(builds)),
        ("design-notes.md", design_notes()),
    ):
        (docs_dir / name).write_text(content)
        written.append(docs_dir / name)

    # docs_dir is written out resolved, and the config path is a parameter, so
    # a build into a temporary directory does not depend on - or overwrite -
    # anything in the repository. Tests do exactly that, and relying on a
    # gitignored docs/ happening to exist is how this broke in CI.
    template = (repo_root / "mkdocs.base.yml").read_text()
    template = re.sub(
        r"^docs_dir:.*$", f"docs_dir: {docs_dir.resolve()}", template, count=1, flags=re.M
    )
    destination = config_path or (repo_root / "mkdocs.yml")
    destination.write_text(template.rstrip() + "\n\n" + _nav(builds))
    return written
