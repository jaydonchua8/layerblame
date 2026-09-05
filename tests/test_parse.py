from layerblame.parse import CACHED, EXECUTED, ERROR, parse_text
from layerblame.report import diff_builds, format_report

SAMPLE = """
#1 [internal] load build definition from Dockerfile
#1 DONE 0.0s

#2 [internal] load metadata for docker.io/library/python:3.12-slim
#2 DONE 0.4s

#4 [1/5] FROM docker.io/library/python:3.12-slim@sha256:abc
#4 CACHED

#5 [2/5] WORKDIR /app
#5 CACHED

#6 [3/5] COPY requirements.txt .
#6 CACHED

#7 [4/5] RUN pip install -r requirements.txt
#7 CACHED

#8 [5/5] COPY . .
#8 DONE 0.3s

#9 exporting to image
#9 DONE 1.1s
"""

BUSTED = SAMPLE.replace(
    "#7 [4/5] RUN pip install -r requirements.txt\n#7 CACHED",
    "#7 [4/5] RUN pip install -r requirements.txt\n#7 DONE 31.7s",
)


def test_parses_every_vertex():
    build = parse_text(SAMPLE)
    assert len(build.steps) == 8


def test_separates_internal_from_build_steps():
    build = parse_text(SAMPLE)
    names = [s.name for s in build.build_steps]
    assert names[0].startswith("FROM")
    assert "load build definition from Dockerfile" not in names


def test_cached_status_survives_a_later_done_line():
    build = parse_text(SAMPLE)
    by_vertex = {s.vertex: s for s in build.steps}
    assert by_vertex[7].status == CACHED
    assert by_vertex[8].status == EXECUTED


def test_steps_sort_by_dockerfile_index_not_vertex_order():
    build = parse_text("\n".join(reversed(SAMPLE.splitlines())))
    indices = [s.index for s in build.build_steps]
    assert indices == sorted(indices)


def test_first_miss_ignores_cheap_instructions():
    build = parse_text(SAMPLE)
    miss = build.first_miss()
    assert miss is not None
    assert miss.instruction == "COPY"
    assert miss.index == 5


def test_first_miss_blames_the_earliest_costly_step():
    build = parse_text(BUSTED)
    miss = build.first_miss()
    assert miss.index == 4
    assert "pip install" in miss.name


def test_wasted_seconds_excludes_cache_hits():
    build = parse_text(BUSTED)
    assert build.wasted_seconds > 31.0
    assert build.wasted_seconds < build.total_seconds + 0.01


def test_error_lines_are_captured():
    build = parse_text("#3 [2/2] RUN false\n#3 ERROR: process did not complete")
    step = build.build_steps[0]
    assert step.status == ERROR
    assert "did not complete" in step.error


def test_named_stage_headers_parse():
    build = parse_text("#5 [builder 3/7] RUN make\n#5 CACHED")
    step = build.build_steps[0]
    assert step.stage == "builder"
    assert step.index == 3
    assert step.total == 7


def test_garbage_lines_are_ignored():
    build = parse_text("not a vertex line\n\n#7 0.123 some stdout\n#7 [1/1] RUN x\n#7 CACHED")
    assert len(build.build_steps) == 1


def test_report_names_the_busting_step():
    out = format_report(parse_text(BUSTED))
    assert "pip install" in out
    assert "Cache broke at step 4/5" in out


def test_report_says_nothing_to_fix_when_fully_cached():
    fully = SAMPLE.replace("#8 DONE 0.3s", "#8 CACHED")
    assert "Nothing to fix" in format_report(parse_text(fully))


def test_diff_flags_a_step_that_stopped_hitting_cache():
    out = diff_builds(parse_text(SAMPLE), parse_text(BUSTED))
    assert "pip install" in out
    assert "cached->MISS" in out
