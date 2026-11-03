# CLAUDE.md

A portfolio project for a prediction-market company interview. It must show low-latency system design, trading knowledge, and AI-native work. The full build plan is at https://claude.ai/artifact/ALHXB9gXzC9oM2NncM43pB.

## Commands

- `uv sync`: install the environment.
- `uv run pytest`: run the tests.
- `uv run ruff check . && uv run ruff format --check . && uv run mypy`: run lint, format, and type checks. CI runs all of these.

## Design rules (do not break these)

- Prices are integer ticks and quantities are integer lots. No floats on the matching path.
- The engine is single-threaded and owns all book state. No locks, I/O, logging, or JSON in the matching loop.
- Engine time is a sequence number plus a simulated nanosecond clock, never wall-clock time. Replaying the same event log must give a byte-identical book hash.
- `obm.engine` must not import from `sim`, `surveillance`, `gateway`, or `dashboard`. It has no third-party runtime dependencies.
- Bots trade only through the engine's command API, never by touching the book.
- The surveillance module reads only the public event stream. It must never see the simulator's hidden `is_spoof` labels.
- Measure before you optimize. Record every optimization and its gain in `BENCHMARKS.md`.

## Performance targets

250,000 messages per second, match latency p50 below 5 µs and p99 below 20 µs, O(1) cancel and best bid/ask, and below 400 MB for 1,000,000 resting orders. All are for pure CPython on one core.

## Phases

1. Core engine: limit, market, IOC, and post-only orders, plus self-trade prevention. Use a tick-indexed array of levels with intrusive linked lists and a `dict` for order lookup. Build a `SortedDict` baseline first in `bench/baselines/` (`sortedcontainers` is a dev dependency only) and benchmark against it. Add unit tests, Hypothesis property tests, and a naive reference engine for differential tests.
2. Event log: a sequencer, fixed-width `struct` records, a ring buffer with a writer thread, snapshots, `replay(log, until_seq)`, a book-hash determinism test, and a latency harness.
3. Agents: a discrete-event simulation with a hidden true value, plus noise, informed, market maker, and spoofer bots. Some noise traders follow book imbalance.
4. Surveillance: per-trader rolling features, then rules, then a model, then optional LLM case files. Report precision, recall, and detection delay. Treat the market maker as the hard false positive.
5. Stretch: a TCP and WebSocket gateway, a live dashboard, a Rust core via PyO3, and binary YES/NO contracts.
