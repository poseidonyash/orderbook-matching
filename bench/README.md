# Benchmarks harness

The load generator and the latency harness go here (Phase 2).

The stream mix is about 60% new orders, 35% cancels, and 5% orders that fill at once. Record per-message latency with `time.perf_counter_ns()` into an HDR histogram. Report p50, p99, p99.9, and the maximum. Copy each result to `BENCHMARKS.md`.
