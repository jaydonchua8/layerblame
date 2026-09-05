# layerblame

Find out which Dockerfile instruction is busting your build cache.

Docker tells you a build took four minutes. It doesn't tell you that one
`COPY . .` near the top invalidated everything under it, and that the slow
`pip install` you keep blaming was only ever a symptom. `layerblame` reads
BuildKit's own progress output and points at the line that actually cost you.

## Install

```sh
pip install layerblame
```

Requires Python 3.9+ and a Docker daemon with BuildKit (default since 23.0).
No third-party dependencies.

## Use

Profile a build as it runs:

```sh
layerblame record .
```

Or profile a log you already have, including one from CI:

```sh
docker build --progress=plain . 2>&1 | layerblame parse -
```

Either way you get:

```
    1/5  cached    0.00s  FROM docker.io/library/python:3.12-slim@sha256:abc
    2/5  cached    0.00s  WORKDIR /app
    3/5  MISS      0.50s  COPY . .
    4/5  MISS     42.80s  RUN pip install -r requirements.txt
    5/5  MISS      0.00s  CMD ["python","app.py"]

  2/5 steps cached, 44.8s total, 44.8s uncached

  Cache broke at step 3/5:
    COPY . .
  That invalidated 3 step(s) below it, costing 43.3s.
  This is a COPY/ADD miss, so a file it reads changed. If it pulls in
  more than it needs, narrow the source paths or add a .dockerignore.
```

The 42.8s `pip install` is the expensive step, but it is not the problem. The
half-second `COPY . .` above it is. Move the dependency install above the
source copy and both come back.

## Commands

| Command | What it does |
| --- | --- |
| `layerblame record [context]` | Run a build, stream it, and save a profile to `.layerblame/` |
| `layerblame report [context]` | Re-print the last recorded run (`--json` for machine output) |
| `layerblame parse <log\|->` | Profile an existing `--progress=plain` log |
| `layerblame diff <old.json> <new.json>` | Show which steps changed cache status between two runs |

`record` passes `-f`, `--target`, and `--build-arg` through to `docker build`,
plus `--docker-arg` for anything else.

## How it works

BuildKit's `--progress=plain` output is a stream of vertex lines. `layerblame`
tracks each vertex's name, `CACHED`/`DONE`/`ERROR` status, and duration, then
orders them by their `[i/n]` step index rather than the order they were
printed, since BuildKit emits vertices concurrently and out of order.

Blame lands on the earliest `RUN`, `COPY`, or `ADD` that missed. Everything
below a miss is invalidated whether or not it would otherwise have hit, so the
first miss is the only line worth fixing. A missed `FROM`, `WORKDIR`, or `CMD`
is ignored — those are free, and blaming them would be noise.

## Caveats

The parser is built against BuildKit's plain output format, which is not a
stable API. It is exercised against the log shapes in `tests/`, including
named build stages, concurrent out-of-order vertices, interleaved step output,
and error lines. If your Docker version prints something it mishandles, open an
issue with the log and it will get a test case.

Durations come from BuildKit's own `DONE` lines, so they measure vertex
execution, not wall-clock build time. Concurrent stages mean the per-step
numbers can add up to more than the build actually took.

## Development

```sh
git clone https://github.com/jaydonchua8/layerblame
cd layerblame
pip install -e ".[dev]"
pytest
```

## License

MIT
