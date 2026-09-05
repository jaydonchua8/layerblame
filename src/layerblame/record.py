"""Run a docker build with plain progress and persist the parsed result."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from .parse import Build, parse_text

STORE_DIRNAME = ".layerblame"


def store_dir(context: str | os.PathLike) -> Path:
    return Path(context) / STORE_DIRNAME


def build_command(
    context: str,
    dockerfile: str | None = None,
    target: str | None = None,
    build_args: list[str] | None = None,
    extra: list[str] | None = None,
) -> list[str]:
    cmd = ["docker", "build", "--progress=plain"]
    if dockerfile:
        cmd += ["-f", dockerfile]
    if target:
        cmd += ["--target", target]
    for arg in build_args or []:
        cmd += ["--build-arg", arg]
    cmd += list(extra or [])
    cmd.append(context)
    return cmd


def run_build(cmd: list[str]) -> tuple[str, int]:
    """Run the build, streaming BuildKit's stderr through while capturing it.

    BuildKit writes progress to stderr, not stdout. We merge both so a build
    that prints to stdout still lands in the same transcript.
    """
    env = dict(os.environ, DOCKER_BUILDKIT="1")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        bufsize=1,
    )
    captured: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        captured.append(line)
        print(line, end="")
    return "".join(captured), proc.wait()


def save_run(context: str, build: Build, log: str, cmd: list[str], exit_code: int) -> Path:
    d = store_dir(context)
    d.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    payload = {
        "recorded_at": stamp,
        "command": cmd,
        "exit_code": exit_code,
        **build.to_dict(),
    }
    path = d / f"run-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2))
    (d / "latest.json").write_text(json.dumps(payload, indent=2))
    (d / f"run-{stamp}.log").write_text(log)
    return path


def load_run(path: str | os.PathLike) -> dict:
    return json.loads(Path(path).read_text())


def latest_run(context: str) -> dict | None:
    p = store_dir(context) / "latest.json"
    return json.loads(p.read_text()) if p.exists() else None


def record(
    context: str,
    dockerfile: str | None = None,
    target: str | None = None,
    build_args: list[str] | None = None,
    extra: list[str] | None = None,
) -> tuple[Build, Path, int]:
    cmd = build_command(context, dockerfile, target, build_args, extra)
    log, exit_code = run_build(cmd)
    build = parse_text(log)
    path = save_run(context, build, log, cmd, exit_code)
    return build, path, exit_code
