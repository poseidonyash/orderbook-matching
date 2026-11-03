# Order Book Matching Engine

A single-instrument exchange in Python. It has three parts:

1. A matching engine with price-time priority. It is single-threaded and deterministic, and it uses integer prices.
2. A market of trading bots: noise traders, an informed trader, a market maker, and a spoofer.
3. A streaming surveillance module that finds the spoofer from order and cancel patterns only.

Status: Phase 1 (core matching engine) has not started.

## Setup

You need [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 if it is not on your machine.

```bash
uv sync
```

The analysis packages (`numpy`, `polars`) are for surveillance work only. To install them too, run `uv sync --all-groups`.

## Commands

```bash
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
uv run mypy              # strict type checks
```

## Layout

```
src/obm/
  engine/        # order.py, book.py, engine.py, types.py
  protocol/      # binary message codecs (struct)
  log/           # sequencer, ring buffer, writer, snapshot, replay
  sim/           # clock, runner, true value
    agents/      # noise, informed, market maker, spoofer
  surveillance/  # features, rules, model, evaluation
  gateway/       # asyncio TCP gateway + WebSocket market data (Phase 5)
  dashboard/     # live dashboard (Phase 5)
bench/           # load generator, latency harness
tests/           # unit, property (Hypothesis), replay determinism
```

## Performance targets

These targets are for pure CPython on one core, measured inside one process.

| Constraint | Target |
| --- | --- |
| Throughput | 250,000 messages per second |
| Match latency, p50 and p99 | Below 5 µs and below 20 µs |
| Cancel by order ID, best bid and ask | O(1) |
| Memory for 1,000,000 resting orders | Below 400 MB |
| Determinism | The same event log gives the same book hash |

Results go in [BENCHMARKS.md](BENCHMARKS.md).
