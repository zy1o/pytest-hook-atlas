"""Command line entry points for capturing traces and building the site."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from . import analysis, build, doclinks, matrix, pypi
from .scenarios import discover

TRACES_DIR = Path("data/traces")
DOCS_DIR = Path("docs")
HEARTBEAT = Path("data/last-checked.json")


def _version_dirs(traces_dir: Path) -> list[Path]:
    if not traces_dir.exists():
        return []
    return sorted(
        (path for path in traces_dir.iterdir() if path.is_dir()),
        key=lambda path: tuple(int(part) if part.isdigit() else 0 for part in path.name.split(".")),
    )


def cmd_build(args: argparse.Namespace) -> int:
    """Render the MkDocs source tree from every captured trace.

    All versions are passed in together: the builder groups them by flow and
    decides which get their own page, so it needs the whole set rather than
    one version's directory.
    """
    versions = _version_dirs(TRACES_DIR)
    if not versions:
        print("no traces captured yet; run 'hook-atlas capture-missing'", file=sys.stderr)
        return 1

    pages = build.build(Path("."), DOCS_DIR, TRACES_DIR, verify_links=not args.no_verify_links)
    print(f"built {len(pages)} pages from {len(versions)} captured releases")
    return 0


def cmd_linkcheck(args: argparse.Namespace) -> int:
    """Verify every documentation anchor the site emits actually resolves.

    This is the check that stops the hook -> docs links rotting silently, which
    is how they broke last time.
    """
    versions = _version_dirs(TRACES_DIR)
    if not versions:
        print("no traces captured yet", file=sys.stderr)
        return 1

    failures = 0
    for version_dir in versions:
        for trace_path in sorted(version_dir.glob("*.json")):
            trace = analysis.load_trace(trace_path)
            base = doclinks.resolve_base_url(trace["environment"]["pytest"])
            page = doclinks.fetch(base)
            for name in sorted(analysis.full_graph(trace).hooks):
                if not doclinks.anchor_exists(page, name):
                    print(f"DEAD  {trace_path.name}  {doclinks.hook_url(name, base)}")
                    failures += 1
            print(f"  {trace_path} -> {base} ok")
    if failures:
        print(f"{failures} dead links", file=sys.stderr)
    return 1 if failures else 0


def _write_heartbeat(checked: int, captured: list[str]) -> None:
    """Record that the watcher ran, even when it found nothing.

    GitHub disables scheduled workflows after 60 days of repository inactivity,
    and pytest release gaps have exceeded that 14 times since 6.0. Writing this
    every run gives the workflow something to commit during a quiet stretch.
    """
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "releases_seen": checked,
                "captured_this_run": captured,
            },
            indent=2,
        )
        + "\n"
    )


def cmd_targets(args: argparse.Namespace) -> int:
    """Show what PyPI offers and what we have already captured."""
    releases = pypi.releases(detailed=args.detailed)
    scenarios = discover(Path("scenarios"))
    already = matrix.captured_versions(TRACES_DIR, scenarios)
    python = args.python or matrix.CURRENT_PYTHON

    print(f"{len(releases)} pytest releases >= {pypi.FLOOR}; python {python}\n")
    print(f"{'version':10} {'released':12} {'state'}")
    for release in releases:
        if release.yanked:
            state = "yanked"
        elif release.version in already:
            state = "captured"
        elif not release.runs_on(python):
            state = f"needs another python ({', '.join(release.pythons) or '?'})"
        else:
            state = "MISSING"
        print(f"{release.version:10} {release.uploaded.date()!s:12} {state}")

    outstanding = matrix.outstanding(releases, TRACES_DIR, python, scenarios=scenarios)
    print(f"\ncapturable now: {len(outstanding)}")
    return 0


def cmd_capture_missing(args: argparse.Namespace) -> int:
    """Capture any pytest release we do not have yet and can run here."""
    releases = pypi.releases(detailed=args.detailed)
    scenarios = discover(Path(args.scenarios))
    python = args.python or matrix.CURRENT_PYTHON
    outstanding = matrix.outstanding(
        releases, TRACES_DIR, python, force=args.force, scenarios=scenarios
    )

    if args.limit:
        outstanding = outstanding[: args.limit]

    if not outstanding:
        print("nothing to capture")
        _write_heartbeat(len(releases), [])
        return 0

    captured, failed = [], []
    with tempfile.TemporaryDirectory(prefix="hook-atlas-matrix-") as workdir:
        for release in outstanding:
            result = matrix.capture_release(release, scenarios, TRACES_DIR, Path(workdir))
            if result.ok:
                captured.append(result.version)
                print(f"  captured pytest {result.version} ({len(result.traces)} scenarios)")
            else:
                failed.append(result.version)
                print(f"  FAILED pytest {result.version}: {result.error}", file=sys.stderr)

    _write_heartbeat(len(releases), captured)
    print(f"\ncaptured {len(captured)}, failed {len(failed)}")
    return 1 if failed and not args.keep_going else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hook-atlas", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="generate the docs tree")
    build_parser.add_argument(
        "--no-verify-links",
        action="store_true",
        help="skip checking that pinned pytest docs exist (offline builds)",
    )
    build_parser.set_defaults(func=cmd_build)

    linkcheck_parser = subparsers.add_parser("linkcheck", help="verify doc anchors")
    linkcheck_parser.set_defaults(func=cmd_linkcheck)

    targets_parser = subparsers.add_parser("targets", help="list pytest releases and their state")
    targets_parser.add_argument("--python", default=None, help='e.g. "3.9"')
    targets_parser.add_argument(
        "--detailed", action="store_true", help="fetch per-release Python support (slower)"
    )
    targets_parser.set_defaults(func=cmd_targets)

    missing_parser = subparsers.add_parser(
        "capture-missing", help="capture pytest releases not yet recorded"
    )
    missing_parser.add_argument("--scenarios", default="scenarios")
    missing_parser.add_argument("--python", default=None)
    missing_parser.add_argument("--limit", type=int, default=0, help="0 means no limit")
    missing_parser.add_argument("--detailed", action="store_true")
    missing_parser.add_argument(
        "--keep-going", action="store_true", help="exit 0 even if some captures failed"
    )
    missing_parser.add_argument(
        "--force",
        action="store_true",
        help="re-capture versions already on disk (only for correcting bad captures)",
    )
    missing_parser.set_defaults(func=cmd_capture_missing)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
