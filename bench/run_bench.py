"""Measure throughput and latency of the order books on the same seeded workload.

Usage:
    uv run python -m bench.run_bench                      # both engines, 1,000,000 messages
    uv run python -m bench.run_bench --engine fast --messages 200000 --seed 7

Each engine runs two passes over the same stream, each on a fresh book:

1. Throughput: one clock read before and one after the whole stream. No clock reads
   inside the loop, so the timer's own cost does not distort the number.
2. Latency: a clock read around every message, recorded in an HDR histogram. Reports
   p50, p99, p99.9 and the maximum, because an average hides the slow messages.

The garbage collector is off during both passes. A collection pause can turn a
3-microsecond message into a 300-microsecond one, and that measures Python, not the book.
"""

import argparse
import gc
import platform
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from hdrh.histogram import HdrHistogram

from bench.baselines.sorted_book import SortedBook
from bench.workload import NewOrder, Workload, generate
from obm.engine.book import OrderBook
from obm.engine.orders import Order, SubmitResult
from obm.engine.types import OrderId


class Book(Protocol):
    def submit(self, order: Order) -> SubmitResult: ...
    def cancel(self, order_id: OrderId) -> bool: ...


ENGINES: dict[str, Callable[[], Book]] = {"fast": OrderBook, "baseline": SortedBook}


@dataclass(frozen=True)
class Result:
    engine: str
    messages: int
    throughput: float  # Messages per second.
    p50_us: float
    p99_us: float
    p999_us: float
    max_us: float


def run(engine: str, workload: Workload) -> Result:
    throughput = _throughput_pass(engine, workload)
    hist = _latency_pass(engine, workload)

    def us(ns: int) -> float:
        return ns / 1_000

    return Result(
        engine=engine,
        messages=len(workload.stream),
        throughput=throughput,
        p50_us=us(hist.get_value_at_percentile(50)),
        p99_us=us(hist.get_value_at_percentile(99)),
        p999_us=us(hist.get_value_at_percentile(99.9)),
        max_us=us(hist.get_max_value()),
    )


def _prepare(engine: str, workload: Workload) -> tuple[Book, list[Order | OrderId]]:
    # Build a warm book and the messages as ready objects, outside any timed section.
    book = ENGINES[engine]()
    for msg in workload.warmup:
        book.submit(msg.to_order())
    items: list[Order | OrderId] = [
        m.to_order() if isinstance(m, NewOrder) else m.id for m in workload.stream
    ]
    return book, items


def _throughput_pass(engine: str, workload: Workload) -> float:
    book, items = _prepare(engine, workload)
    submit, cancel = book.submit, book.cancel
    with _gc_off():
        start = time.perf_counter_ns()
        for item in items:
            if isinstance(item, Order):
                submit(item)
            else:
                cancel(item)
        elapsed = time.perf_counter_ns() - start
    return len(items) / (elapsed / 1e9)


def _latency_pass(engine: str, workload: Workload) -> HdrHistogram:
    book, items = _prepare(engine, workload)
    submit, cancel = book.submit, book.cancel
    clock = time.perf_counter_ns
    latencies = [0] * len(items)  # Fill a list first: recording into the histogram costs time.
    with _gc_off():
        for i, item in enumerate(items):
            if isinstance(item, Order):
                t0 = clock()
                submit(item)
                latencies[i] = clock() - t0
            else:
                t0 = clock()
                cancel(item)
                latencies[i] = clock() - t0
    hist = HdrHistogram(1, 10_000_000_000, 3)  # 1 ns to 10 s, 3 significant digits.
    for ns in latencies:
        hist.record_value(max(ns, 1))
    return hist


class _gc_off:
    def __enter__(self) -> None:
        gc.collect()
        gc.freeze()  # Move existing objects out of the collector's view.
        gc.disable()

    def __exit__(self, *exc: object) -> None:
        gc.enable()
        gc.unfreeze()


def markdown_row(result: Result, label: str) -> str:
    return (
        f"| {time.strftime('%Y-%m-%d')} | {label} ({result.engine}) | "
        f"{result.throughput:,.0f} | {result.p50_us:.2f} | {result.p99_us:.2f} | "
        f"{result.p999_us:.2f} | {result.max_us:.1f} | {result.messages:,} messages |"
    )


def machine() -> str:
    return (
        f"{platform.processor() or platform.machine()}, {platform.system()} "
        f"{platform.release()}, Python {platform.python_version()}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", choices=["fast", "baseline", "both"], default="both")
    parser.add_argument("--messages", type=int, default=1_000_000)
    parser.add_argument("--warmup", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--label", default="Phase 1", help="Change column for BENCHMARKS.md")
    args = parser.parse_args()

    print(f"Generating {args.messages:,} messages (seed {args.seed})...")
    workload = generate(args.seed, args.messages, args.warmup)
    engines = ["fast", "baseline"] if args.engine == "both" else [args.engine]

    print(f"Machine: {machine()}\n")
    for engine in engines:
        result = run(engine, workload)
        print(
            f"{engine:>8}: {result.throughput:>12,.0f} msg/s   p50 {result.p50_us:6.2f} us   "
            f"p99 {result.p99_us:6.2f} us   p99.9 {result.p999_us:7.2f} us   "
            f"max {result.max_us:9.1f} us"
        )
        print(markdown_row(result, args.label))


if __name__ == "__main__":
    main()
