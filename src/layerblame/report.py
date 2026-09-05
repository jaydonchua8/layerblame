"""Render a parsed build into something you can act on."""

from __future__ import annotations

from .parse import Build, Step, CACHED, EXECUTED, ERROR

MARK = {CACHED: "cached", EXECUTED: "MISS", ERROR: "ERROR", "unknown": "?"}


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "\u2026"


def format_table(build: Build, width: int = 64) -> str:
    rows = []
    for step in build.build_steps:
        label = f"{step.index}/{step.total}" if step.index else "-"
        rows.append(
            f"  {label:>7}  {MARK[step.status]:<6} {step.seconds:>7.2f}s  "
            f"{_truncate(step.name, width)}"
        )
    return "\n".join(rows)


def format_summary(build: Build) -> str:
    steps = build.build_steps
    cached = sum(1 for s in steps if s.status == CACHED)
    lines = [
        "",
        f"  {cached}/{len(steps)} steps cached, "
        f"{build.total_seconds:.1f}s total, "
        f"{build.wasted_seconds:.1f}s uncached",
    ]

    miss = build.first_miss()
    if miss is None:
        lines.append("  Fully cached. Nothing to fix.")
        return "\n".join(lines)

    after = [s for s in build.build_steps if s.index and miss.index and s.index >= miss.index]
    downstream = sum(s.seconds for s in after)
    lines += [
        "",
        f"  Cache broke at step {miss.index}/{miss.total}:",
        f"    {miss.name}",
        f"  That invalidated {len(after)} step(s) below it, costing {downstream:.1f}s.",
    ]
    if miss.instruction in ("COPY", "ADD"):
        lines.append(
            "  This is a COPY/ADD miss, so a file it reads changed. If it pulls in\n"
            "  more than it needs, narrow the source paths or add a .dockerignore."
        )
    elif miss.instruction == "RUN":
        lines.append(
            "  This is a RUN miss, so an earlier layer changed underneath it. Move\n"
            "  it above whatever invalidated it, or split it out."
        )
    return "\n".join(lines)


def format_report(build: Build) -> str:
    return format_table(build) + "\n" + format_summary(build)


def diff_builds(old: Build, new: Build) -> str:
    """Compare two runs step by step, showing what changed cache status."""
    old_by_name = {s.name: s for s in old.build_steps}
    lines = []
    for step in new.build_steps:
        prev = old_by_name.get(step.name)
        if prev is None:
            lines.append(f"  + new    {_truncate(step.name, 60)}")
        elif prev.status != step.status:
            lines.append(
                f"  ~ {MARK[prev.status]}->{MARK[step.status]:<6} "
                f"{_truncate(step.name, 52)}"
            )
    removed = {s.name for s in old.build_steps} - {s.name for s in new.build_steps}
    for name in sorted(removed):
        lines.append(f"  - gone   {_truncate(name, 60)}")
    return "\n".join(lines) if lines else "  No change in cache behaviour between runs."
