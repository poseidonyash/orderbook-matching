"""Smoke tests for the benchmark code. They check that it works, not how fast it is:
shared CI machines give timings that vary too much to test."""

from bench.run_bench import run
from bench.workload import Cancel, NewOrder, generate

from obm.engine.types import OrderType


def test_same_seed_gives_the_same_workload() -> None:
    assert generate(seed=3, messages=500, warmup_orders=100) == generate(
        seed=3, messages=500, warmup_orders=100
    )


def test_workload_has_the_planned_mix() -> None:
    stream = generate(seed=1, messages=20_000, warmup_orders=2_000).stream

    cancels = sum(isinstance(m, Cancel) for m in stream) / len(stream)
    iocs = sum(isinstance(m, NewOrder) and m.type == OrderType.IOC for m in stream) / len(stream)

    assert 0.32 < cancels < 0.38
    assert 0.03 < iocs < 0.07


def test_benchmark_runs_on_both_engines() -> None:
    workload = generate(seed=1, messages=2_000, warmup_orders=200)

    for engine in ("fast", "baseline"):
        result = run(engine, workload)
        assert result.messages == 2_000
        assert result.throughput > 0
        assert 0 < result.p50_us <= result.p99_us <= result.p999_us <= result.max_us
