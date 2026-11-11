"""Differential test: the fast book and the baseline must agree on random order streams.

The baseline is simple enough to trust by reading. If the fast book gives the same fills
and the same best prices after every step, for thousands of random steps, it follows the
same rules.
"""

import random

import pytest
from bench.baselines.sorted_book import SortedBook

from obm.engine.book import OrderBook
from obm.engine.orders import Order
from obm.engine.types import OrderId, OrderType, Price, Qty, Side, TraderId


@pytest.mark.parametrize("seed", range(50))
def test_random_stream_gives_identical_results(seed: int) -> None:
    rng = random.Random(seed)
    fast = OrderBook(Price(1), Price(100))
    base = SortedBook()
    submitted: list[OrderId] = []

    for step in range(400):
        if submitted and rng.random() < 0.3:
            # Cancel a random earlier order. It may already be filled or cancelled.
            oid = rng.choice(submitted)
            assert fast.cancel(oid) == base.cancel(oid), f"step {step}: cancel {oid}"
        else:
            oid = OrderId(len(submitted) + 1)
            side = rng.choice([Side.BUY, Side.SELL])
            price = Price(rng.randint(45, 55))  # A narrow range, so orders cross often.
            qty = Qty(rng.randint(1, 10))
            # Mostly limit orders, so the book fills up, plus some of each other type.
            kind = rng.choices(list(OrderType), weights=[70, 10, 10, 10])[0]
            submitted.append(oid)
            # Each book gets its own Order object, because books change the quantity.
            fast_result = fast.submit(Order(oid, TraderId(0), side, price, qty, kind))
            base_result = base.submit(Order(oid, TraderId(0), side, price, qty, kind))
            assert fast_result == base_result, f"step {step}: order {oid} ({kind.name})"

        assert fast.best_bid() == base.best_bid(), f"step {step}: best bid"
        assert fast.best_ask() == base.best_ask(), f"step {step}: best ask"
