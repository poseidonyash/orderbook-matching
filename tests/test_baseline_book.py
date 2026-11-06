"""Tests for the SortedDict baseline order book (limit orders only, for now)."""

from bench.baselines.sorted_book import Order, SortedBook
from obm.engine.types import OrderId, Price, Qty, Side, TraderId


def order(id: int, side: Side, price: int, qty: int, trader: int = 0) -> Order:
    return Order(OrderId(id), TraderId(trader), side, Price(price), Qty(qty))


def test_empty_book_has_no_best_prices() -> None:
    book = SortedBook()

    assert book.best_bid() is None
    assert book.best_ask() is None


def test_buy_sweeps_two_levels() -> None:
    # Example 1: the buyer takes the cheaper 52s first, then 2 lots at 53.
    book = SortedBook()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=10))
    book.submit(order(id=2, side=Side.SELL, price=53, qty=5))

    fills = book.submit(order(id=3, side=Side.BUY, price=53, qty=12))

    assert [(f.maker_id, f.taker_id, f.price, f.qty) for f in fills] == [
        (1, 3, 52, 10),
        (2, 3, 53, 2),
    ]
    assert book.best_ask() == 53
    assert book.best_bid() is None


def test_unfilled_remainder_rests_as_a_bid() -> None:
    # Example 2: 53 is above the buyer's limit, so 2 lots rest as a bid at 52.
    book = SortedBook()
    book.submit(order(id=1, side=Side.SELL, price=52, qty=10))
    book.submit(order(id=2, side=Side.SELL, price=53, qty=5))

    fills = book.submit(order(id=3, side=Side.BUY, price=52, qty=12))

    assert [(f.maker_id, f.price, f.qty) for f in fills] == [(1, 52, 10)]
    assert book.best_bid() == 52
    assert book.best_ask() == 53
