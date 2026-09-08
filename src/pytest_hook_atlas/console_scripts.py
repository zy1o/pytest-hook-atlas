"""Command line entry points for capturing traces and building the site."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pytest

from . import analysis, build, doclinks
from .scenarios import capture, discover

TRACES_DIR = Path("data/traces")
DOCS_DIR = Path("docs")


def _version_dirs(traces_dir: Path) -> list[Path]:
    if not traces_dir.exists():
        return []
    return sorted(
        (path for path in traces_dir.iterdir() if path.is_dir()),
        key=lambda path: tuple(int(part) if part.isdigit() else 0 for part in path.name.split(".")),
    )


def cmd_capture(args: argparse.Namespace) -> int:
    """Run every scenario under the tracer and commit the JSON."""
    destination = TRACES_DIR / pytest.__version__
    scenarios = discover(Path(args.scenarios))
    if not scenarios:
        print(f"no scenarios found in {args.scenarios}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="hook-atlas-") as workdir:
        for scenario in scenarios:
            trace_path = capture(scenario, destination / f"{scenario.id}.json", Path(workdir))
            trace = analysis.load_trace(trace_path)
            print(
                f"  {scenario.id:24} {trace['stats']['total_calls']:5} calls, "
                f"{trace['stats']['unique_hooks']:3} hooks -> {trace_path}"
            )
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Render the MkDocs source tree from captured traces."""
    versions = _version_dirs(TRACES_DIR)
    if not versions:
        print("no traces captured yet; run 'hook-atlas capture' first", file=sys.stderr)
        return 1

    traces = TRACES_DIR / args.pytest_version if args.pytest_version else versions[-1]
    if not traces.exists():
        print(f"no traces for pytest {args.pytest_version}", file=sys.stderr)
        return 1

    pages = build.build(Path("."), DOCS_DIR, traces, verify_links=not args.no_verify_links)
    print(f"built {len(pages)} pages from {traces} into {DOCS_DIR}/")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hook-atlas", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture", help="trace every scenario")
    capture_parser.add_argument("--scenarios", default="scenarios")
    capture_parser.set_defaults(func=cmd_capture)

    build_parser = subparsers.add_parser("build", help="generate the docs tree")
    build_parser.add_argument("--pytest-version", default=None)
    build_parser.add_argument(
        "--no-verify-links",
        action="store_true",
        help="skip checking that pinned pytest docs exist (offline builds)",
    )
    build_parser.set_defaults(func=cmd_build)

    linkcheck_parser = subparsers.add_parser("linkcheck", help="verify doc anchors")
    linkcheck_parser.set_defaults(func=cmd_linkcheck)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
