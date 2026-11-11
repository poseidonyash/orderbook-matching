# CLAUDE.md

A portfolio project for a prediction-market company interview. It must show low-latency system design, trading knowledge, and AI-native work. The full build plan is in `docs/PLAN.md`. Read the section for the current phase before you start work on it.

## How we work

The owner is building this project to learn it well enough to explain every part in an interview. Follow this loop for every feature:

1. Branch. One feature per branch, named `phaseN/<feature>`, and one pull request per feature.
2. Teach first. Explain the concept the feature needs in plain words, with a small worked example in numbers.
3. Design questions. Ask the owner the design questions that matter, each with the options, the trade-off, and a recommendation. Wait for answers before writing code.
4. Build. Write the code and tests. Keep the diff small enough to read in one sitting.
5. Walkthrough. Explain the finished code in reading order: which part does what, and why.
6. Explain-back check. Ask two or three interview-style questions about the feature. The owner answers in their own words. Correct anything wrong or vague.
7. Notes. Add the feature's entry to `docs/INTERVIEW_NOTES.md`: the concept, the decisions and their reasons, the trade-offs, and the interview questions with the owner's corrected answers.
8. Pull request. The description lists the design decisions and their reasons. The owner reviews and merges.

Do not add Claude attribution lines to commits or pull requests.

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
