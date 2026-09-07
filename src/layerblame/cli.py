"""layerblame command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .parse import Build, Step, parse_text
from .record import DockerUnavailable, latest_run, load_run, record, store_dir
from .report import diff_builds, format_report


def _build_from_payload(payload: dict) -> Build:
    steps = []
    for raw in payload.get("steps", []):
        raw = {k: v for k, v in raw.items() if k != "instruction"}
        steps.append(Step(**raw))
    return Build(steps=steps)


def cmd_record(args: argparse.Namespace) -> int:
    try:
        build, path, exit_code = record(
            args.context,
            dockerfile=args.file,
            target=args.target,
            build_args=args.build_arg,
            extra=args.docker_arg,
        )
    except DockerUnavailable as exc:
        print(f"layerblame: {exc}", file=sys.stderr)
        return 2
    print("\n" + format_report(build))
    print(f"\n  Saved to {path}")
    return exit_code


def cmd_report(args: argparse.Namespace) -> int:
    payload = load_run(args.run) if args.run else latest_run(args.context)
    if payload is None:
        print(
            f"No runs recorded in {store_dir(args.context)}. "
            "Run `layerblame record` first.",
            file=sys.stderr,
        )
        return 1
    build = _build_from_payload(payload)
    if args.json:
        print(json.dumps(build.to_dict(), indent=2))
    else:
        print(format_report(build))
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    text = Path(args.logfile).read_text() if args.logfile != "-" else sys.stdin.read()
    build = parse_text(text)
    if args.json:
        print(json.dumps(build.to_dict(), indent=2))
    else:
        print(format_report(build))
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    old = _build_from_payload(load_run(args.old))
    new = _build_from_payload(load_run(args.new))
    print(diff_builds(old, new))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="layerblame",
        description="Find out which Dockerfile instruction is busting your build cache.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="run a docker build and profile its cache use")
    rec.add_argument("context", nargs="?", default=".", help="build context (default: .)")
    rec.add_argument("-f", "--file", help="path to Dockerfile")
    rec.add_argument("--target", help="build stage to target")
    rec.add_argument("--build-arg", action="append", help="passed through to docker build")
    rec.add_argument(
        "--docker-arg",
        action="append",
        help="extra raw flag for docker build (repeatable)",
    )
    rec.set_defaults(func=cmd_record)

    rep = sub.add_parser("report", help="show the last recorded run")
    rep.add_argument("context", nargs="?", default=".")
    rep.add_argument("--run", help="path to a specific run-*.json")
    rep.add_argument("--json", action="store_true", help="machine-readable output")
    rep.set_defaults(func=cmd_report)

    par = sub.add_parser("parse", help="profile a build log you already have")
    par.add_argument("logfile", help="file containing --progress=plain output, or - for stdin")
    par.add_argument("--json", action="store_true")
    par.set_defaults(func=cmd_parse)

    dif = sub.add_parser("diff", help="compare cache behaviour between two runs")
    dif.add_argument("old")
    dif.add_argument("new")
    dif.set_defaults(func=cmd_diff)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
