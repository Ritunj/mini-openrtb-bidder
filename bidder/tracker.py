"""
Purpose:
    Record what happens in the simulator: every auction's outcome, and
    every confirmed impression (win notice).

Responsibilities:
    - log_auction(...): append one entry to the bid log for EVERY auction,
      whatever its outcome ("bid", "no_bid" or "invalid"), so the dashboard
      can show not just what we bid on but WHY we did not bid.
    - record_win(...): handle a win notice idempotently and store the
      confirmed impression (Feature 6).

Dependencies:
    - datetime (standard library), bidder.storage
"""

from datetime import datetime, timezone

from bidder import storage


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string, e.g. 2026-07-06T09:15:32+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_auction(result: str, request_id, reason: str | None = None,
                bid_id: str | None = None, campaign_id: str | None = None,
                creative_id: str | None = None,
                price: float | None = None) -> dict:
    """
    Purpose: Append one entry to the bid log -- the simulator's flight
             recorder. Called once per auction, for every outcome.
    Input:   result - "bid", "no_bid" or "invalid";
             request_id - the incoming request's id (may be None if the
             request was too broken to have one);
             reason - human-readable explanation for no_bid/invalid;
             bid_id / campaign_id / creative_id / price - filled in only
             for "bid" results (Module 7 uses bid_id to find this entry
             again when the win notice arrives).
    Output:  The entry that was stored.
    Example: log_auction("no_bid", "req-1", reason="no campaigns exist yet")
    """
    entry = {
        "timestamp": _now_iso(),
        "request_id": request_id,
        "result": result,
    }
    # Only include the fields that apply to this outcome, so the log stays
    # easy to read in an editor.
    if reason is not None:
        entry["reason"] = reason
    if bid_id is not None:
        entry["bid_id"] = bid_id
    if campaign_id is not None:
        entry["campaign_id"] = campaign_id
    if creative_id is not None:
        entry["creative_id"] = creative_id
    if price is not None:
        entry["price"] = price

    storage.append_record(storage.BID_LOG_FILE, entry,
                          max_entries=storage.BID_LOG_MAX_ENTRIES)
    return entry


def record_win(bid_id: str, win_price: float | None):
    """
    Purpose: Close the auction loop (Feature 6). The exchange fired our
             nurl to say bid_id won, so store the confirmed impression.
    Input:   bid_id - the winning bid's id (from the nurl query string);
             win_price - the clearing price the exchange substituted into
             the ${AUCTION_PRICE} macro, or None if it was missing or
             unparseable -- in which case we fall back to our own bid
             price (i.e. we assume a first-price auction).
    Output:  The impression record, or None if bid_id is unknown.
             IDEMPOTENT: a second notice for the same bid returns the
             already-stored impression instead of recording a duplicate --
             in real adtech a double-recorded impression is a
             double-billed advertiser.
    Example: record_win("bid_1a2b3c", 1.87)
    """
    # Duplicate win notice? Return what we already stored, record nothing.
    impressions = storage.load_json(storage.IMPRESSIONS_FILE)
    for impression in impressions:
        if impression.get("bid_id") == bid_id:
            return impression

    # Find the original bid in the flight recorder. This lookup is exactly
    # why Module 6 stored bid_id/campaign_id/creative_id/price on every
    # "bid" entry: the log doubles as our pending-bids index.
    bid_entry = None
    for entry in storage.load_json(storage.BID_LOG_FILE):
        if entry.get("result") == "bid" and entry.get("bid_id") == bid_id:
            bid_entry = entry
            break
    if bid_entry is None:
        return None

    bid_price = float(bid_entry.get("price", 0.0))
    impression = {
        "bid_id": bid_id,
        "campaign_id": bid_entry.get("campaign_id"),
        "creative_id": bid_entry.get("creative_id"),
        "bid_price": bid_price,                 # what we offered
        "win_price": win_price if win_price is not None else bid_price,
        "timestamp": _now_iso(),
    }
    storage.append_record(storage.IMPRESSIONS_FILE, impression)
    return impression
