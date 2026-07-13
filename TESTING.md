# Testing Guide

Everything here assumes the server is running in another terminal: `python app.py`

There are three ways to test, from fastest to most thorough:

1. **Dashboard** — open <http://localhost:5000/>, use the test console.
2. **curl with the sample files** — every request in `samples/` is ready to send.
3. **Automated run** — `python samples/run_tests.py` resets the data files,
   seeds through the API, fires every sample file, and asserts all the
   expected outputs below (plus the win-notice edge cases). Exit code 0 = all green.

## Setup / reset

```bash
python samples/seed.py        # create the 3 sample campaigns + 3 creatives
```

Seeding is append-only (the API deliberately has no update/delete). For a clean
slate, either run `run_tests.py` (which resets first) or set each file in
`data/` back to `[]`.

The seed set is engineered so every sample below has exactly one verdict:

| Campaign | CPM | Status | Targeting | Creative |
|---|---|---|---|---|
| Diwali Sale - IND Mobile | 2.50 | active | IND · mobile · IAB12 | 300×250 |
| Global Desktop News | 1.50 | active | any country · desktop · any category | 728×90 |
| Paused Premium | 9.00 | **paused** | IND | 300×250 |

Paused Premium exists to prove a point: it outbids everyone and must never win.

## Expected outputs — sample bid requests

Send any file with:

```bash
curl -i -X POST http://localhost:5000/openrtb/bid \
     -H "Content-Type: application/json" \
     -d @samples/bid_request_match.json
```

| File | Scenario | Expected verdict |
|---|---|---|
| `bid_request_match.json` | IND · mobile · IAB12 · 300×250 · floor 1.0 | **200** — Diwali bids **2.50** (9.00 campaign is paused) |
| `bid_request_desktop.json` | USA · desktop · 728×90 · floor 0.5 | **200** — WorldCo bids **1.50** (any-country targeting) |
| `bid_request_no_match_geo.json` | USA · mobile · 300×250 | **204** — geo excludes Diwali; device+size exclude WorldCo |
| `bid_request_no_match_size.json` | IND · mobile · **160×600** | **204** — nobody owns a skyscraper creative |
| `bid_request_high_floor.json` | perfect match but floor **5.0** | **204** — every active bid is below the floor |
| `bid_request_video.json` | impression with **no banner** object | **204** — valid OpenRTB (video imp); a banner DSP declines, never errors |
| `bid_request_invalid.json` | empty `imp`, `site` is a string | **400** — both problems listed in `details` |

Every auction, including the 204s and the 400, appears in the dashboard's
"Recent auctions" table with a `reason` — that table is the first place to look
when a request doesn't do what you expected.

## Creating your own data

`samples/campaign_example.json` and `samples/creative_example.json` are
ready-to-edit request bodies for the two creation endpoints:

```bash
curl -X POST http://localhost:5000/api/campaigns \
     -H "Content-Type: application/json" -d @samples/campaign_example.json
# copy the returned "id" into creative_example.json, then:
curl -X POST http://localhost:5000/api/creatives \
     -H "Content-Type: application/json" -d @samples/creative_example.json
```

## Edge cases — win notice & lifecycle

A win notice needs a live `bid_id`, so these can't be static files. After any
200 bid response, copy the `nurl` and:

| Edge case | How to test | Expected |
|---|---|---|
| Second-price win | Fire the `nurl` with `${AUCTION_PRICE}` replaced by e.g. `1.87` | 200; impression stores `bid_price: 2.5`, `win_price: 1.87` |
| Duplicate win notice | Fire the exact same URL again | 200, same record; `impressions.json` still has ONE entry |
| Unsubstituted macro | Fire the `nurl` verbatim (macro left in) | 200; `win_price` falls back to the bid price |
| Unknown bid | `curl "localhost:5000/win?bid_id=bid_ghost&price=1"` | 404 |
| Missing bid_id | `curl "localhost:5000/win?price=1"` | 400 |
| Empty database | Reset `data/`, send `bid_request_match.json` | 204; log reason: "no campaigns exist yet" |
| Bare request | POST `{"id":"x","imp":[{"id":"1","banner":{"w":300,"h":250}}]}` | 204 — unknown country can never satisfy IND targeting |
| Lowercase country | Change `"IND"` to `"ind"` in `bid_request_match.json` | Still 200 — signals are normalised |

## Manual dashboard checklist

- [ ] `GET /` loads; campaigns/creatives tables show the 3 seeded rows, "Paused Premium" wears an amber badge
- [ ] Test console is prefilled; **Send bid request** → green "HTTP 200 — we bid!" with the full OpenRTB response
- [ ] Win panel appears; **Fire win notice** → impression JSON shown and the Impressions table gains a row
- [ ] Edit the floor to `5.0`, send → amber 204 message; "Recent auctions" explains why
- [ ] Delete a comma in the textarea, send → red 400 with the validator's details
- [ ] **Refresh** re-renders without duplicating rows
- [ ] Every id, price and timestamp renders in monospace; ad markup shows as text, never as rendered HTML

## Automated run — expected result

```
$ python samples/run_tests.py
...
RESULT: 19 passed, 0 failed
```
