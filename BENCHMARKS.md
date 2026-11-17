# Benchmarks

Each row records one measured run. Every run uses the same seeded workload, one core, one process, and the garbage collector turned off during the timed sections.

To reproduce a row:

```bash
uv run python -m bench.run_bench --messages 1000000 --seed 1
```

Machine: Intel Core, family 6 model 154 (12th generation, laptop), Windows 11, Python 3.12.13.

Workload (seed 1): the book starts with 10,000 resting limit orders. Then 1,000,000 timed messages follow:

- About 60% are limit orders that rest within 50 ticks of the middle price.
- About 35% are cancels of resting orders.
- About 5% are IOC orders that trade at once.

The book grows during the run, from 10,000 to about 208,000 resting orders. At the end, each of the 95 price levels holds about 2,200 orders.

## Results

Latencies are in microseconds (µs). Throughput is in messages per second.

| Date | Change | Throughput | p50 | p99 | p99.9 | Max | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-11-17 | Phase 1 (fast) | 354,153 | 2.40 | 12.01 | 42.02 | 11,075.6 | 1,000,000 messages |
| 2026-11-17 | Phase 1 (baseline) | 37,752 | 7.80 | 217.73 | 755.20 | 27,459.6 | 1,000,000 messages |

## Against the Phase 1 targets

| Target | Fast book | Met |
| --- | --- | --- |
| 250,000 messages per second | 354,153 | Yes |
| p50 below 5 µs | 2.40 µs | Yes |
| p99 below 20 µs | 12.01 µs | Yes |

## What the numbers say

The fast book handles 9.4 times more messages per second than the baseline, and its p99 is 18 times lower. The main reason is cancel. The baseline removes an order from the middle of a deque, so a cancel searches the queue at that price. With about 2,200 orders at each price, that search is long. The fast book unlinks the order from its neighbours, in the same time for any queue length. The gap grows with the size of the book.

The maximum latency of both books is in the milliseconds. One message in a million is slow, and the p99.9 shows that this is rare. On a laptop, the operating system sometimes pauses the process to run other work. A machine set up for low latency removes most of these pauses, for example with a reserved CPU core. The garbage collector is off during the run, so it is not the cause.

Memory use and the cost of the walk to the next best price in a sparse book are not measured yet.
