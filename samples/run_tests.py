"""
Purpose:
    Automated verification of the whole simulator: reset the data files,
    seed via the real API, fire every sample bid request FILE at the
    server, and assert each documented expected output plus the
    win-notice edge cases. This makes TESTING.md executable.

Responsibilities:
    - Reset data/ to a clean slate (the one file-touching privilege this
      test utility takes; the app itself only touches disk via storage.py)
    - Seed from seed_data.json through POST /api/campaigns|creatives
    - POST each samples/bid_request_*.json exactly as stored on disk,
      so the shipped files themselves are what gets verified
    - Check the win-notice lifecycle: record, idempotency, 404, 400

Dependencies:
    - json, urllib, pathlib (standard library only)

Usage:
    python app.py                 (in one terminal)
    python samples/run_tests.py   (in another; resets data/ first!)
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
SAMPLES_DIR = Path(__file__).resolve().parent
DATA_DIR = SAMPLES_DIR.parent / "data"

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


def call(method: str, path: str, raw_body: bytes | None = None):
    """Send a request; return (status, parsed JSON or None, body length)."""
    headers = {"Content-Type": "application/json"} if raw_body else {}
    request = urllib.request.Request(BASE_URL + path, data=raw_body,
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None), len(raw)
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, (json.loads(raw) if raw else None), len(raw)


def post_json(path: str, body: dict) -> dict:
    status, parsed, _ = call("POST", path, json.dumps(body).encode("utf-8"))
    if status not in (200, 201):
        sys.exit(f"Seeding failed on {path}: HTTP {status} {parsed}")
    return parsed


def send_sample(filename: str):
    """POST a sample file byte-for-byte as stored on disk."""
    return call("POST", "/openrtb/bid", (SAMPLES_DIR / filename).read_bytes())


def main() -> None:
    print("Resetting data files to a clean slate...")
    for name in ("campaigns", "creatives", "bid_log", "impressions"):
        (DATA_DIR / f"{name}.json").write_text("[]", encoding="utf-8")

    print("Seeding via the API...")
    seed = json.loads((SAMPLES_DIR / "seed_data.json").read_text(encoding="utf-8"))
    ids_by_name = {}
    for campaign in seed["campaigns"]:
        created = post_json("/api/campaigns", campaign)
        ids_by_name[created["name"]] = created["id"]
    for creative in seed["creatives"]:
        body = dict(creative)
        body["campaign_id"] = ids_by_name[body.pop("campaign_name")]
        post_json("/api/creatives", body)

    print("\nSeeded state")
    _, campaigns, _ = call("GET", "/api/campaigns")
    _, creatives, _ = call("GET", "/api/creatives")
    check("3 campaigns exist", len(campaigns) == 3)
    check("3 creatives exist", len(creatives) == 3)

    print("\nSample files -> expected verdicts")
    status, response, _ = send_sample("bid_request_match.json")
    bid = response["seatbid"][0]["bid"][0] if status == 200 else {}
    check("match.json -> 200", status == 200)
    check("match.json -> Diwali wins at 2.50 (paused 9.00 never bids)",
          bid.get("price") == 2.5)
    check("match.json -> response id echoes req-demo-1", response.get("id") == "req-demo-1")
    check("match.json -> nurl carries the ${AUCTION_PRICE} macro",
          "${AUCTION_PRICE}" in bid.get("nurl", ""))
    match_nurl = bid.get("nurl", "")

    status, response, _ = send_sample("bid_request_desktop.json")
    check("desktop.json -> 200, WorldCo wins at 1.50",
          status == 200 and response["seatbid"][0]["bid"][0]["price"] == 1.5)

    status, _, size = send_sample("bid_request_no_match_geo.json")
    check("no_match_geo.json -> 204 with empty body", status == 204 and size == 0)

    status, _, size = send_sample("bid_request_no_match_size.json")
    check("no_match_size.json (160x600) -> 204", status == 204 and size == 0)

    status, _, size = send_sample("bid_request_high_floor.json")
    check("high_floor.json (floor 5.0) -> 204", status == 204 and size == 0)

    status, _, size = send_sample("bid_request_video.json")
    check("video.json (no banner) -> valid request, 204", status == 204 and size == 0)

    status, response, _ = send_sample("bid_request_invalid.json")
    check("invalid.json -> 400 listing every problem",
          status == 400 and len(response.get("details", [])) >= 2)

    print("\nFlight recorder")
    _, log, _ = call("GET", "/api/log")
    check("all 7 auctions logged", len(log) == 7)
    check("log is newest-first", log[0]["request_id"] == "req-invalid-1"
          and log[-1]["request_id"] == "req-demo-1")
    check("every no_bid entry has a reason",
          all(e.get("reason") for e in log if e["result"] == "no_bid"))

    print("\nWin-notice lifecycle (Feature 6 edge cases)")
    win_path = match_nurl.replace(BASE_URL, "").replace("${AUCTION_PRICE}", "1.87")
    status, impression, _ = call("GET", win_path)
    check("win at 1.87 -> bid_price 2.5 and win_price 1.87 stored",
          status == 200 and impression["bid_price"] == 2.5
          and impression["win_price"] == 1.87)

    status, _, _ = call("GET", win_path)
    _, impressions, _ = call("GET", "/api/impressions")
    check("duplicate win notice -> idempotent (still exactly 1 impression)",
          status == 200 and len(impressions) == 1)

    status, _, _ = call("GET", "/win?bid_id=bid_ghost&price=1.0")
    check("unknown bid_id -> 404", status == 404)

    status, _, _ = call("GET", "/win?price=1.0")
    check("missing bid_id -> 400", status == 400)

    print(f"\nRESULT: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError:
        sys.exit("Could not reach the server. Start it first:  python app.py")
