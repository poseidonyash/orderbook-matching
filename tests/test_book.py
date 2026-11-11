"""Tests for the parts of the fast OrderBook that the baseline does not have."""

import pytest

from obm.engine.book import Level, OrderBook
from obm.engine.orders import Order
from obm.engine.types import OrderId, Price, Qty, Side, TraderId


def order(id: int, side: Side, price: int, qty: int) -> Order:
    return Order(OrderId(id), TraderId(0), side, Price(price), Qty(qty))


def queue(level: Level) -> list[int]:
    # Walk the linked list from head to tail, and check the back links on the way.
    ids: list[int] = []
    node = level.head
    prev = None
    while node is not None:
        assert node.prev is prev
        ids.append(node.id)
        prev, node = node, node.next
    assert level.tail is prev
    return ids


def test_level_append_and_remove_keep_links_consistent() -> None:
    level = Level()
    a, b, c = (order(i, Side.SELL, 52, 1) for i in (1, 2, 3))
    for o in (a, b, c):
        level.append(o)
    assert queue(level) == [1, 2, 3]
    assert level.qty == 3

    level.remove(b)  # Middle.
    assert queue(level) == [1, 3]
    level.remove(a)  # Head.
    assert queue(level) == [3]
    level.remove(c)  # Last one.
    assert queue(level) == []
    assert (level.head, level.tail, level.qty) == (None, None, 0)


def test_best_ask_skips_empty_ticks_when_the_best_level_empties() -> None:
    book = OrderBook(Price(1), Price(99))
    book.submit(order(1, Side.SELL, 52, 1))
    book.submit(order(2, Side.SELL, 55, 1))

    book.submit(order(3, Side.BUY, 52, 1))  # Empties 52.

    assert book.best_ask() == 55


def test_best_bid_skips_empty_ticks_when_the_best_level_is_cancelled() -> None:
    book = OrderBook(Price(1), Price(99))
    book.submit(order(1, Side.BUY, 50, 1))
    book.submit(order(2, Side.BUY, 47, 1))

    book.cancel(OrderId(1))

    assert book.best_bid() == 47


def test_cancel_below_the_best_price_leaves_the_best_price() -> None:
    book = OrderBook(Price(1), Price(99))
    book.submit(order(1, Side.BUY, 50, 1))
    book.submit(order(2, Side.BUY, 47, 1))

    book.cancel(OrderId(2))

    assert book.best_bid() == 50


def test_book_empties_completely() -> None:
    book = OrderBook(Price(1), Price(99))
    book.submit(order(1, Side.SELL, 99, 2))  # Top tick of the range.
    book.submit(order(2, Side.BUY, 1, 2))  # Bottom tick of the range.

    book.submit(order(3, Side.BUY, 99, 2))
    book.submit(order(4, Side.SELL, 1, 2))

    assert (book.best_bid(), book.best_ask()) == (None, None)


@pytest.mark.parametrize("price", [0, 100])
def test_price_outside_the_range_is_rejected(price: int) -> None:
    book = OrderBook(Price(1), Price(99))
    with pytest.raises(ValueError, match="outside"):
        book.submit(order(1, Side.BUY, price, 1))


@pytest.mark.parametrize("qty", [0, -1])
def test_non_positive_quantity_is_rejected(qty: int) -> None:
    book = OrderBook(Price(1), Price(99))
    with pytest.raises(ValueError, match="positive"):
        book.submit(order(1, Side.BUY, 50, qty))


def test_duplicate_resting_order_id_is_rejected() -> None:
    book = OrderBook(Price(1), Price(99))
    book.submit(order(1, Side.BUY, 50, 1))
    with pytest.raises(ValueError, match="already resting"):
        book.submit(order(1, Side.BUY, 49, 1))
