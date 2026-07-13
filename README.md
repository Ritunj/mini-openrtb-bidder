# Mini OpenRTB Bidder Simulator

An educational Demand-Side Platform (DSP) bidder that demonstrates the complete
OpenRTB 2.x real-time bidding lifecycle, end to end:

```
OpenRTB Bid Request ──▶ Validate ──▶ Match campaigns ──▶ Select winner & price
        ──▶ OpenRTB Bid Response (with win-notice nurl) ──▶ Win notice ──▶ Impression recorded
```

Built as a 2026 internship project. It is a **proof of concept for learning
purposes** — deliberately not production-ready, with every simplification
documented in [Design decisions & limitations](#design-decisions--known-limitations).

## Features

All six features required by the project brief are implemented and covered by
the automated test suite (`python samples/run_tests.py` → 19 checks):

| # | Feature | Where |
|---|---------|-------|
| 1 | Create a campaign with targeting parameters | `POST /api/campaigns` |
| 2 | Register a creative and associate it with a campaign | `POST /api/creatives` |
| 3 | HTTP endpoint accepting OpenRTB bid requests | `POST /openrtb/bid` |
| 4 | Rule-based matching of active campaigns against the request | `bidder/matcher.py` |
| 5 | Valid OpenRTB bid response on match, spec-correct no-bid otherwise | `bidder/bidding.py` → `200` / `204` |
| 6 | Win-notice simulation and impression confirmation | `GET /win` → `data/impressions.json` |

Plus a small dashboard (`GET /`) with live tables and a test console that can
send bid requests and fire win notices — the whole lifecycle in four clicks.

## Architecture

One Flask process, three layers:

1. **Web layer** — `app.py`: every HTTP route. Parses input, calls one logic
   module, shapes output. Contains no business logic.
2. **Logic layer** — the `bidder/` package. Pure Python, no Flask imports,
   fully testable with plain dicts.
3. **Storage layer** — `bidder/storage.py`: the only code that touches disk.

| Module | Responsibility | Production parallel |
|--------|----------------|---------------------|
| `bidder/validator.py` | Checks every incoming payload; returns *all* problems at once | Request validation stage of a bidder |
| `bidder/matcher.py` | Six ordered targeting rules → matching (campaign, creative) pairs | Campaign service + bid evaluation |
| `bidder/bidding.py` | Internal auction (highest CPM wins) + OpenRTB response assembly | Pricing engine (where ML lives in real DSPs) |
| `bidder/tracker.py` | Logs every auction outcome; records win notices idempotently | Tracking service |
| `bidder/storage.py` | JSON file read/write, id generation | The Redis/PostgreSQL layer, reduced to files |

A production DSP runs these responsibilities as separate services connected by
queues and caches because it answers ~100k auctions per second in under 100 ms.
This simulator keeps the same separation of concerns as *modules inside one
process* — identical architecture, none of the infrastructure.

### The matching rules (in fail-fast order)

1. Campaign `status` is `active`
2. Geo — request country ∈ `targeting.countries`
3. Device — mapped `device.devicetype` ∈ `targeting.device_types`
4. Context — `site.cat` overlaps `targeting.site_categories`
5. Price — campaign `cpm_bid` ≥ impression `bidfloor`
6. Creative — the campaign owns a creative exactly matching the banner's `w`×`h`

An empty targeting list means "no restriction". A *missing* request signal can
never satisfy a restriction — targeting is a promise to the advertiser, and
unknown ≠ allowed.

## Technology choices

| Choice | Why |
|--------|-----|
| Python + Flask | Minimal and readable; every request handler is a plain function. Only dependency: `flask` (pinned in `requirements.txt`). |
| Flat JSON files | Zero-setup persistence you can open in any editor; plays the role a database plays in a real DSP, and makes every state change inspectable. |
| Vanilla HTML/CSS/JS | No build step, no framework. The dashboard renders all data via `textContent`, so user-supplied ad markup can never inject scripts. |

## Project structure

```
mini-openrtb-bidder/
├── app.py                    # Flask app + all HTTP routes (web layer)
├── requirements.txt          # flask, pinned to the tested version
├── README.md                 # this file
├── TESTING.md                # expected outputs, edge cases, checklists
├── bidder/                   # business logic package (see Architecture)
│   ├── validator.py          #   input validation (campaigns, creatives, bid requests)
│   ├── matcher.py            #   the six targeting rules
│   ├── bidding.py            #   winner selection + OpenRTB response builder
│   ├── tracker.py            #   auction log + win-notice/impression recording
│   └── storage.py            #   the only module that reads/writes data/
├── data/                     # the "database": four flat JSON files (start as [])
│   ├── campaigns.json
│   ├── creatives.json
│   ├── bid_log.json          #   every auction outcome; doubles as win-notice lookup
│   └── impressions.json      #   confirmed (won) impressions
├── static/                   # dashboard CSS + vanilla JS
├── templates/dashboard.html  # the single dashboard page
└── samples/                  # ready-to-send payloads + scripts
    ├── seed_data.json        #   3 campaigns + 3 creatives, engineered for the demos
    ├── seed.py               #   loads seed data through the real API
    ├── run_tests.py          #   automated suite: resets, seeds, verifies (19 checks)
    ├── bid_request_*.json    #   7 OpenRTB requests, one deterministic verdict each
    ├── campaign_example.json #   ready-to-edit body for POST /api/campaigns
    └── creative_example.json #   ready-to-edit body for POST /api/creatives
```

## Installation & setup

Requires **Python 3.10+** and `pip`. No database, no other services.

```bash
# 1. Clone
git clone https://github.com/<your-username>/mini-openrtb-bidder.git
cd mini-openrtb-bidder

# 2. Virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux

# 3. Dependencies (just Flask)
pip install -r requirements.txt

# 4. Run
python app.py
```

Verify: open <http://localhost:5000/> (dashboard) or
`curl http://localhost:5000/api/health` →
`{"service": "mini-openrtb-bidder", "status": "ok"}`.

## Quick demo (the 2-minute walkthrough)

```bash
python samples/seed.py         # 3 campaigns + 3 creatives, via the real API
```

Then in the dashboard at <http://localhost:5000/>:

1. The tables show three campaigns — note "Paused Premium" bids 9.00 but wears
   an amber *paused* badge. It exists to prove the status rule: it never wins.
2. **Send bid request** (the console is prefilled) → green `HTTP 200` with the
   full OpenRTB response. Diwali wins at 2.50 despite the 9.00 campaign.
3. **Fire win notice** at a lower clearing price (e.g. 1.87) → the impression
   appears with `bid_price: 2.5` and `win_price: 1.87` — second-price
   economics, captured in data.
4. Change the request's `bidfloor` to `5.0`, send → amber `204`, and the
   auction log's *reason* column explains why.

Prefer the terminal? Every scenario is a file:

```bash
curl -i -X POST http://localhost:5000/openrtb/bid \
     -H "Content-Type: application/json" \
     -d @samples/bid_request_match.json
```

See **[TESTING.md](TESTING.md)** for the full expected-outputs table, edge
cases, and the manual checklist — or run everything automatically:

```bash
python samples/run_tests.py    # resets data, seeds, asserts: 19 passed, 0 failed
```

## API reference

Every route's docstring in `app.py` documents Purpose / Input / Output /
Example. Summary:

| Method & path | Purpose | Responses |
|---------------|---------|-----------|
| `POST /api/campaigns` | Create a campaign (Feature 1) | `201`, `400` |
| `GET /api/campaigns` | List campaigns | `200` |
| `POST /api/creatives` | Create a creative linked to a campaign (Feature 2) | `201`, `400` |
| `GET /api/creatives` | List creatives | `200` |
| `POST /openrtb/bid` | **The auction** (Features 3–5) | `200` bid · `204` no-bid · `400` invalid |
| `GET /win?bid_id=&price=` | **Win notice** → record impression (Feature 6) | `200`, `400`, `404` |
| `GET /api/log` | Auction log, newest first | `200` |
| `GET /api/impressions` | Confirmed impressions, newest first | `200` |
| `GET /api/health` | Liveness check | `200` |
| `GET /` | Dashboard | `200` |

The bid response plants a `nurl` of the form
`http://<host>/win?bid_id=<id>&price=${AUCTION_PRICE}`. The `${AUCTION_PRICE}`
macro is defined by the OpenRTB spec: the *exchange* substitutes the clearing
price when firing the URL on a win. If it arrives unsubstituted, the simulator
falls back to the bid price (first-price behaviour).

## Design decisions & known limitations

Intentional simplifications of a learning prototype — each is the honest answer
to "what would production do differently?":

- **First impression only.** Multi-`imp` requests are valid; we evaluate
  `imp[0]` and say so in the code.
- **Banner only, single `w`/`h`.** A request without a banner (video/native) is
  *valid* OpenRTB and gets a spec-correct `204` no-bid — never a `400`. The
  2.x `format` array of sizes is not supported.
- **Flat CPM pricing.** The campaign's configured CPM is the bid. Production
  prices with predicted CTR × value, pacing, and more — that logic would slot
  into `bidding.select_winner()` without touching anything else.
- **Win notice = impression.** OpenRTB 2.5 separates the win notice (`nurl`)
  from billing (`burl`); we treat one idempotent `nurl` hit as the confirmed
  impression.
- **The bid log doubles as the win-notice index** and keeps only the newest
  100 entries — a win notice arriving more than 100 auctions after its bid
  would 404. Irrelevant at demo scale; a production system uses a dedicated
  pending-bids store.
- **`cur` and `tmax` are ignored.** We always bid USD, at whatever speed.
  Real exchanges drop bidders that miss the ~100 ms `tmax` deadline — the very
  reason production DSPs need the caching/queueing infrastructure this project
  deliberately omits.
- **Floats for prices** (rounded to 4 decimals). Production uses integer
  micro-units to avoid floating-point drift in billing.
- **Country codes are not validated as ISO-3166-1 alpha-3** — a campaign
  targeting `"INDIA"` would silently never match `"IND"` requests.
- **Creation only** — no update/pause/delete endpoints (the brief requires
  creation), and no authentication, budgets, or pacing.
- **Single-user, single-process.** The Flask dev server handles one request at
  a time, so the read-modify-write JSON storage needs no locking.
- **`GET /win` has side effects**, which breaks REST purity but matches the
  OpenRTB spec exactly: exchanges fire `nurl` as a GET.
- **Code style:** PEP 8 with a 99-character line limit (explicitly permitted by
  PEP 8 for teams); verified with `flake8`.

## Future improvements

1. Evaluate every impression in multi-`imp` requests and support the `format`
   size array.
2. Daily budgets and pacing (spend tracked per campaign at win time).
3. Smarter bidding: a pluggable scoring function in `select_winner()` — the
   slot where production DSPs run predicted-CTR models.
4. Campaign lifecycle endpoints (update, pause, archive) and budget-aware
   status.
5. A dedicated pending-bids store with expiry, replacing the bid-log lookup.
6. Swap `storage.py`'s internals for SQLite without changing its interface —
   a one-module migration by design.
7. Honour `tmax` (respond within the deadline or not at all) and `cur`.
8. The production hardening studied in the accompanying research report:
   real datastores and caches, horizontal scaling, streaming pipelines for
   impression/click events, and ML-driven bid optimisation.

## Project context

Developed as the prototype component of an internship on programmatic
advertising and OpenRTB bidder systems (research report + working prototype).
The simulator exists to demonstrate understanding of the RTB lifecycle;
correctness and clarity were prioritised over scale by design.
