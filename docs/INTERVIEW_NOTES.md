# Interview notes

One entry per feature, written as the project grows. Each entry records what the feature does, why it is built this way, and how to explain it in an interview. The answers are in my own words, corrected during review.

Read this file before an interview. The newest feature is at the bottom.

## Template

### Feature name (pull request link)

What it does: one or two sentences.

Key concept: the idea from trading or computer science that the feature depends on.

Decisions:

| Decision | Choice | Why | What I gave up |
| --- | --- | --- | --- |
| | | | |

Interview questions:

- Question: ...
  Answer: ...

## 1. Baseline order book

What it does: a simple order book that matches limit orders on both sides with price-time priority, and cancels resting orders by id. It uses a `SortedDict` of price levels, and each level is a `deque` of orders, oldest first. It is the reference that the fast engine is checked and measured against.

Why two engines: the baseline is simple, so it is easy to trust by reading it. The fast engine (next feature) must give exactly the same fills for the same orders. A differential test sends one random order stream to both and compares the fills. The benchmark runs the same stream through both, which gives a measured speed-up.

Key concept: price-time priority. The best price fills first. For a buyer, the best price is the lowest ask. At the same price, the oldest order fills first. A trade happens at the resting (maker) order's price, not the incoming (taker) order's price. Whatever part of the incoming order does not fill rests in the book.

Worked example: the book holds asks of 10 lots at 52 and 5 lots at 53. A buy of 12 lots at 53 trades 10 at 52, then 2 at 53. Three lots stay at 53. With a limit of 52 instead, only 10 lots trade, and 2 lots rest as a bid at 52.

Decisions:

| Decision | Choice | Why | What I gave up |
| --- | --- | --- | --- |
| Where `Order` and `Fill` live | `src/obm/engine/orders.py`, shared by both engines | Both engines must produce the same `Fill` objects so that their outputs can be compared. The engine must not import from `bench/`. | The baseline is no longer one self-contained file. |
| Data structure | `SortedDict` of price to `deque` of orders | Simple and clearly correct. Sorted keys give the best price, and the deque keeps time order. | Speed. Looking up a level costs O(log n) in the number of price levels. |
| Cancel | A `dict` from order id to order, then `deque.remove` | The benchmark sends about 35% cancels, so the baseline needs cancel for a fair comparison. | Cancel costs O(n) in the orders at that price. The fast engine fixes this. |
| `Order` equality | `eq=False`: each order equals only itself | Two different orders can have the same fields. They are still different orders. | Nothing in practice. |
| `Fill` | `frozen=True` | A fill records a trade that already happened, so no code can change it. | Nothing in practice. |

Interview questions:

- Question: A buyer bids up to 60, and the only seller asks 52. At what price do they trade, and why?
  Answer: At 52, the resting seller's price. The trade always happens at the maker's price. The seller was in the book first and offered 52. The buyer's 60 is only a limit: the most the buyer agrees to pay. When the book offers a lower price, the buyer pays that lower price. When more asks exist, the same rule holds: each fill uses the price of the order it trades against.

- Question: How does the time for `cancel` grow with the number of orders at one price, and why?
  Answer: It grows linearly, O(n), not exponentially. A deque is O(1) only at its two ends: adding at the back and removing from the front. To remove an order from the middle, `deque.remove` must walk from the front and compare each order until it finds the right one. With 1,000 orders at a price, a cancel can check up to 1,000 orders. The fast engine keeps a doubly linked list: each order stores links to the order before it and the order after it. The engine finds the order through the id dictionary. Then it removes the order by changing two links, in the same time for any queue length.

- Question: Why can an `Order` change, while a `Fill` is frozen?
  Answer: An order's remaining quantity goes down each time it partly fills, so the engine must change it in place. A fill is a record of a trade that already happened. No code can change it afterward. The class is frozen, so an attempt to change a field raises an error.
