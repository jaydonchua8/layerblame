"""Parse `docker build --progress=plain` (BuildKit) output into structured steps.

BuildKit writes progress to stderr as a stream of vertex lines, all prefixed
with `#N` where N is the vertex number. The lines we care about:

    #7 [4/9] RUN pip install -r requirements.txt      <- header (name)
    #7 CACHED                                          <- status
    #7 DONE 12.4s                                      <- status + duration
    #7 ERROR: process did not complete successfully    <- status
    #7 3.201 Collecting flask                          <- step output (ignored)

Vertex numbers are not emitted in order and a vertex's header can appear long
after its status line, so we accumulate into a dict keyed by number and sort at
the end. Ordering uses the `[i/n]` step index when present, falling back to
vertex number for internal vertices that have no step index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Iterable

# `#7 [4/9] RUN foo` and also `#7 [builder 4/9] RUN foo` for named stages.
_HEADER = re.compile(
    r"^#(?P<vertex>\d+)\s+"
    r"\[(?:(?P<stage>[^\]]*?)\s+)?(?P<index>\d+)/(?P<total>\d+)\]\s+"
    r"(?P<name>.*)$"
)
# `#3 [internal] load metadata for docker.io/library/python:3.12`
_INTERNAL = re.compile(r"^#(?P<vertex>\d+)\s+\[internal\]\s+(?P<name>.*)$")
# `#7 3.201 Collecting flask` — a timestamped line of the step's own output.
_OUTPUT = re.compile(r"^#\d+\s+\d+\.\d+\s")
# `#9 exporting to image` — a named vertex with no [i/n] header. Not a
# Dockerfile instruction, so it is filed alongside the internal vertices.
_NAMED = re.compile(r"^#(?P<vertex>\d+)\s+(?P<name>\S.*)$")
_CACHED = re.compile(r"^#(?P<vertex>\d+)\s+CACHED\s*$")
_DONE = re.compile(r"^#(?P<vertex>\d+)\s+DONE\s+(?P<secs>[0-9.]+)s\s*$")
_ERROR = re.compile(r"^#(?P<vertex>\d+)\s+ERROR:?\s*(?P<msg>.*)$")

CACHED = "cached"
EXECUTED = "executed"
ERROR = "error"
UNKNOWN = "unknown"

# Instructions whose execution actually costs build time. `layerblame` blames the
# first of these that misses; a missed FROM or ARG is noise, not a cache bust.
COSTLY = ("RUN", "COPY", "ADD")


@dataclass
class Step:
    vertex: int
    name: str = ""
    status: str = UNKNOWN
    seconds: float = 0.0
    index: int | None = None
    total: int | None = None
    stage: str | None = None
    internal: bool = False
    error: str = ""

    @property
    def instruction(self) -> str:
        """The Dockerfile verb, e.g. RUN / COPY / FROM. Empty if unknown."""
        return self.name.split(" ", 1)[0].upper() if self.name else ""

    @property
    def costly(self) -> bool:
        return self.instruction in COSTLY

    @property
    def sort_key(self) -> tuple:
        # Real build steps first (ordered by their [i/n] index), then internal
        # vertices in vertex order.
        return (1 if self.internal else 0, self.index if self.index else 0, self.vertex)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["instruction"] = self.instruction
        return d


@dataclass
class Build:
    steps: list[Step] = field(default_factory=list)

    @property
    def build_steps(self) -> list[Step]:
        """Steps that came from Dockerfile instructions, excluding internals.

        A vertex only counts as a build step if BuildKit gave it an `[i/n]`
        index. Export, load and other bookkeeping vertices have names but no
        index, and blaming them for a cache miss would be nonsense.
        """
        return [s for s in self.steps if not s.internal and s.index is not None]

    @property
    def total_seconds(self) -> float:
        return sum(s.seconds for s in self.steps)

    @property
    def wasted_seconds(self) -> float:
        """Time spent in steps that were not served from cache."""
        return sum(s.seconds for s in self.steps if s.status != CACHED)

    def first_miss(self) -> Step | None:
        """The earliest costly step that was not served from cache.

        Everything after this point is invalidated regardless of whether it
        would otherwise have hit, so this is the single line worth fixing.
        """
        for step in self.build_steps:
            if step.costly and step.status in (EXECUTED, ERROR):
                return step
        return None

    def to_dict(self) -> dict:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "total_seconds": round(self.total_seconds, 3),
            "wasted_seconds": round(self.wasted_seconds, 3),
        }


def parse_lines(lines: Iterable[str]) -> Build:
    """Parse BuildKit plain output into a Build. Unrecognised lines are ignored."""
    steps: dict[int, Step] = {}

    def get(vertex: int) -> Step:
        return steps.setdefault(vertex, Step(vertex=vertex))

    for raw in lines:
        line = raw.rstrip("\n").strip()
        if not line.startswith("#") or _OUTPUT.match(line):
            continue

        if m := _HEADER.match(line):
            step = get(int(m.group("vertex")))
            step.name = m.group("name").strip()
            step.index = int(m.group("index"))
            step.total = int(m.group("total"))
            step.stage = m.group("stage")
            continue

        if m := _INTERNAL.match(line):
            step = get(int(m.group("vertex")))
            step.name = m.group("name").strip()
            step.internal = True
            continue

        if m := _CACHED.match(line):
            get(int(m.group("vertex"))).status = CACHED
            continue

        if m := _DONE.match(line):
            step = get(int(m.group("vertex")))
            step.seconds = float(m.group("secs"))
            # CACHED is emitted before DONE for cache hits; don't overwrite it.
            if step.status != CACHED:
                step.status = EXECUTED
            continue

        if m := _ERROR.match(line):
            step = get(int(m.group("vertex")))
            step.status = ERROR
            step.error = m.group("msg").strip()
            continue

        if m := _NAMED.match(line):
            step = get(int(m.group("vertex")))
            if not step.name:
                step.name = m.group("name").strip()
                step.internal = True
            continue

    ordered = sorted(steps.values(), key=lambda s: s.sort_key)
    return Build(steps=ordered)


def parse_text(text: str) -> Build:
    return parse_lines(text.splitlines())
