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

## 2. Fast order book

What it does: the same matching rules as the baseline, in `src/obm/engine/book.py`. Level lookup, adding an order, cancel, and reading the best bid or ask each take the same time for any book size.

Key concepts:

- Tick-indexed array. Prices are whole ticks in a fixed range, so the book keeps one level for each possible price. The price is the index: the level at 52 is `levels[52]`.
- Intrusive doubly linked list. Each order stores `prev` and `next`, the orders in front of it and behind it in its queue. A level stores only `head` (oldest) and `tail` (newest). "Intrusive" means that the links live inside the order object, so the book creates no extra node objects.
- Stored best prices with sentinels. The book keeps the best bid and best ask in two variables. An empty side holds a fake price one tick outside the range, so the matching loop needs no special check for an empty side.

Worked example: three orders wait at 52: A, then B, then C. To cancel B, the book finds B in the id dictionary, then sets A's `next` to C and C's `prev` to A. Nothing walks the queue.

Decisions:

| Decision | Choice | Why | What I gave up |
| --- | --- | --- | --- |
| Price range | Set when the book is created, default 1 to 10,000. Prices outside it are rejected. | One engine fits different markets, for example 1 to 99 cents for a prediction market. | Memory for every tick in the range, even ticks with no orders. |
| Where the links live | `prev` and `next` fields on the shared `Order` | No extra node object for each resting order, so less memory and less work. | `Order` carries two fields that the baseline does not use. |
| Next best price after a level empties | Walk the array tick by tick | Simple. In a busy market the next price is one or two ticks away. Measure first, then optimize. | In a sparse book with wide gaps, the walk is slow. |
| Buy and sell loops | Two mirrored methods instead of one general method | Each loop stays short and has no side checks inside it. | Some repeated code. |
| Proof of correctness | Behaviour tests on both books, plus a differential test against the baseline | Random streams reach cases that nobody writes by hand. | A bug that both books share is not caught by the differential test. |

Interview questions:

- Question: Why does a cancel take the same time with 3 or 3,000 orders at one price?
  Answer: Two things. The id dictionary finds the order in one step, so the book does not search for it. The order's price is its index in the level array, so the book finds its level in one step too. Then the doubly linked list removes the order by changing two links: the order in front now points to the order behind, and the reverse. No step walks through the queue.

- Question: The asks are at 52 and 60, and the last order at 52 fills. How does the book find the new best ask, and when is that slow?
  Answer: It walks up the array from 53. It checks 53, 54 and so on, finds each level empty, and stops at 60, the first level with orders. That takes one step for each empty tick, here 8 steps. It is slow in an illiquid, sparse book, where the gaps between prices with orders are wide. In a 1 to 99 cent market the walk is at most 98 steps. In a wide range with large gaps it can be thousands of steps. The benchmark feature measures this before we change anything.

- Question: The differential test has no hand-written expected fills. How can it prove anything?
  Answer: It uses the baseline as the expected answer. The baseline is simple enough to check by reading, and the behaviour tests check it with hand-written cases. If the fast book gives the same fills and best prices after each step of 20,000 random steps, it follows the same rules, including in cases that nobody thought to write. Its limit: a bug that both books share passes the test, which is why the hand-written tests also run on both books.

## 3. Order types

What it does: both books accept four order types: limit, market, IOC (immediate-or-cancel) and post-only. `submit` now returns a `SubmitResult` with the fills and an `Outcome`: `RESTED`, `FILLED`, `CANCELLED` or `REJECTED`.

Key concept: an order type changes only two things. One is the limit price for matching. The other is what happens to the remainder. The matching loop is the same for every type.

| Type | Limit for matching | Remainder | Who uses it |
| --- | --- | --- | --- |
| Limit | The order's price | Rests in the book | Most orders |
| Market | None: the far edge of the range | Cancelled | Traders who care about speed more than price |
| IOC | The order's price | Cancelled | Traders who want to take liquidity without leaving a visible order |
| Post-only | Never matches | Rests. The order is rejected instead if it can trade on arrival. | Market makers, who want maker rebates instead of taker fees |

Worked example: the book holds asks of 10 at 52 and 5 at 53.

- Market buy of 20: trades 10 at 52 and 5 at 53. The last 5 lots are cancelled.
- IOC buy of 12 at 52: trades 10 at 52. The last 2 lots are cancelled. As a limit order, those 2 lots rest as a bid at 52.
- Post-only buy at 52: rejected, because it can trade against the ask at 52. At 51, it rests.

Decisions:

| Decision | Choice | Why | What I gave up |
| --- | --- | --- | --- |
| How an order carries its type | A `type` field on `Order`, default `LIMIT` | Existing calls keep working, and the event log can record the type with the order. | `Order` gets one more field. |
| Market order price | Ignored. The engine uses the edge of the range as the limit. | The matching loop needs no special case. | No price protection: a large market order in a thin book trades at bad prices. Real exchanges add a price band. This is a stretch goal. |
| How submit reports results | `SubmitResult(fills, outcome)` | The caller can tell a rested remainder from a cancelled one, and a rejected order is a normal result, not an error. | Callers changed from a list of fills to a result object. The Phase 2 event log replaces it with full events. |
| Baseline | Gets the same four types | The differential test then covers the types too. | A little more code in the baseline. |

Testing note: to make sure that the differential test works, I planted a bug in the fast book: an IOC remainder that rested like a limit order. The differential test failed and caught it.

Interview questions:

- Question: The book holds asks of 10 at 52 and 5 at 53. A market buy for 20 arrives. What happens?
  Answer: It trades 10 at 52, then 5 at 53. No asks are left, and 5 lots remain. They are cancelled, not rested. To rest, an order needs a price to wait at, and a market order has no price. It means "give me what is available now". The engine reports `CANCELLED`.

- Question: Why is a rejected post-only order an outcome, while an out-of-range price raises an error?
  Answer: An out-of-range price is a caller mistake: the engine cannot use that order at all, so it raises an error. A post-only order that can trade is a valid order. Post-only means "add me to the book only as a maker". The engine followed that instruction, and the trader's program reads the result and reacts. An error is for something that must never happen. An outcome is for something that happens every day.

- Question: How does the engine handle a market order without changing the matching loop?
  Answer: The loop trades while the best ask is at or below a limit. For a market buy, the engine sets the limit to the highest tick in the range, so every ask passes. All the type-specific work happens outside the loop: the engine picks the limit before the loop and decides the fate of the remainder after it.

## 4. Self-trade prevention

What it does: a trader's incoming order never trades with that same trader's resting order. The engine cancels the resting order instead, and matching goes on with the next order in the queue. `SubmitResult.self_trade_cancels` lists the cancelled ids.

Key concept: a self-trade (on purpose, a wash trade) prints a trade where no money changes hands. It makes the market look busier than it is and can move the last traded price. Regulators ban wash trades. It also happens by accident, for example when a market maker's quotes move fast and its new buy crosses its own sell. Exchanges call the protection STP (self-trade prevention).

Worked example: trader 7 rests a sell of 10 at 52 (order 1). Trader 9 rests a sell of 5 at 52 behind it (order 2). Trader 7 sends a buy of 8 at 52 (order 3). The engine cancels order 1 with no trade. Order 3 then trades 5 at 52 with order 2. The last 3 lots of order 3 rest as a bid at 52.

STP methods on real exchanges:

| Method | What happens | In this project |
| --- | --- | --- |
| Cancel resting | The old order goes, and the new order keeps matching | Yes |
| Cancel incoming | The new order stops, and the old order stays | No |
| Cancel both | Both orders go | No |
| Decrement | Both orders shrink by the overlap, and nothing trades | No |

Decisions:

| Decision | Choice | Why | What I gave up |
| --- | --- | --- | --- |
| STP method | Cancel resting, one rule for the whole engine | The newest order shows what the trader wants now. In the loop, it is the same as removing a filled maker. | Traders cannot choose a method for each order. A field on `Order` can add that later. |
| How the trader learns of the cancel | `self_trade_cancels` on `SubmitResult` | Without it, the trader's program still believes that the order rests. The Phase 2 event log turns these into `Cancelled` events. | One more field on the result. |
| Post-only against an own order | Rejected, like any post-only order that crosses | Post-only never enters the matching loop, so one rule covers both cases. | Nothing. |
| Trader ids in tests | Each test order is its own trader by default. The differential test uses 5 traders. | No test self-trades by accident, and the random test hits self-trades often. | Tests that want a self-trade must name the trader. |

Testing note: with STP turned off in the fast book only, the differential test failed, so it guards this rule.

Interview questions:

- Question: Trader 7 rests a sell of 10 at 52, and trader 9 rests a sell of 5 at 52 behind it. Trader 7 sends a buy of 8 at 52. What happens to each order?
  Answer: Trader 7's resting sell is cancelled without a trade, because it belongs to the same trader. The buy goes on and trades 5 at 52 with trader 9, whose order is then complete. The buy has 3 lots left, and as a limit order they rest as a bid at 52. The result lists the cancelled order in `self_trade_cancels`.

- Question: Why stop a trader from trading with themself, when no money changes hands?
  Answer: The trade still counts in the market data. It shows volume that is not real and can move the last price, which misleads other traders. Done on purpose, it is a wash trade, which regulators ban. By accident, it costs the trader fees for nothing. Stopping it in the engine protects the market data and the trader.

- Question: How does STP fit into the matching loop?
  Answer: After the loop picks the maker, it compares the maker's trader with the incoming order's trader. If they are the same, there is no fill, and the maker is removed exactly like a fully filled maker. Then the loop goes on to the next order. The rest of the loop does not change.

## 5. Property-based tests

What it does: a Hypothesis state machine in `tests/test_book_properties.py` builds sequences of submits and cancels. It runs each sequence on the fast book and the baseline side by side, and it checks a set of rules after every step. It replaces the earlier random-seed differential test.

Key concept: a property-based test states a rule that must be true for every input, instead of one hand-written example. A tool, here Hypothesis, searches for an input that breaks the rule. Two features make it stronger than plain random tests. It tries edge cases on purpose, such as the top and bottom tick, a quantity of 1, or a cancel of an order that just filled. When it finds a failure, it shrinks it to the shortest input that still fails. Stateful testing applies this to systems with actions, like an order book: Hypothesis builds sequences of actions and checks the rules after each one.

The rules (invariants) checked after every step:

| Rule | Why it must hold |
| --- | --- |
| Both books give the same results and the same depth | The baseline is the reference. |
| The fast book's structures are consistent: links, level totals, id map, best prices | Fast code keeps the same facts in several places, and they must agree. |
| Best bid is below best ask | If they meet, those orders trade at once. A crossed book is a bug. |
| No quantity appears or disappears | Each order's sent quantity equals filled, plus resting, plus cancelled. |
| Each fill is at the maker's price and inside the taker's limit | Price-time priority and the limit rule. |
| No fill has the same trader on both sides | Self-trade prevention. |

Decisions:

| Decision | Choice | Why | What I gave up |
| --- | --- | --- | --- |
| Test style | Stateful `RuleBasedStateMachine` with submit and cancel rules | Matches how a book runs, checks every rule after every step, and shrinks to the shortest failing sequence. | Harder to read than a simple list of operations. |
| How tests see inside the books | Public `depth(side)` on both books, and `check_invariants()` on the fast book, for tests only | `depth` is the market data snapshot that a later feature needs. Tests do not depend on private fields. | `check_invariants` visits every tick, so it is far too slow for the matching path. |
| Old random differential test | Deleted | The state machine compares both books at every step and adds shrinking. | Nothing: it tested the same thing. |
| An independent record of every order | The test tracks sent, filled, cancelled and resting for each order | Two books that share a bug agree with each other. The record catches that case. | More test code. |

Testing note: with a planted bug (a fill that does not lower its level's total), Hypothesis failed and shrank the problem to two or three orders. `check_invariants` named the fault: `level total 1 != 0`.

Interview questions:

- Question: Why is a failing sequence of 3 orders more useful than one of 287 steps?
  Answer: With 3 orders, I can work out by hand what the book must do and see where it went wrong, in a minute. With 287 steps, most of them have nothing to do with the bug, and I must find the important few myself. Hypothesis shrinking does that search for me: it removes steps and simplifies values while the failure stays.

- Question: Why does the test keep its own record of each order, when it can compare the two books?
  Answer: Comparison only proves that the two books agree. If both have the same bug, they agree and the test passes. The record does not depend on either book: it adds up fills and cancels from the results and checks that every lot is accounted for. That is a third, independent view.
