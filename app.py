"""
Purpose:
    Entry point of the Mini OpenRTB Bidder Simulator.
    Creates the Flask application and defines all HTTP routes (the web layer).

Responsibilities:
    - Start the Flask development server
    - Define routes: parse HTTP input, call ONE bidder module, shape HTTP output
    - Contain NO business logic (all logic lives in the bidder/ package)

Dependencies:
    - Flask (web framework)
    - bidder/ package (modules are wired in one at a time during Phase 4)
"""

from flask import Flask, jsonify, render_template, request

from bidder import bidding, matcher, storage, tracker, validator

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    """
    Purpose: Serve the dashboard page.
    Input:   None (browser GET request).
    Output:  Rendered HTML page (templates/dashboard.html).
    Example: Open http://localhost:5000/ in a browser.
    """
    return render_template("dashboard.html")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    """
    Purpose: Confirm the server is up (setup sanity check).
    Input:   None.
    Output:  200 + JSON {"status": "ok", "service": "mini-openrtb-bidder"}.
    Example: curl http://localhost:5000/api/health
    """
    return jsonify({"status": "ok", "service": "mini-openrtb-bidder"})


# ---------------------------------------------------------------------------
# Campaigns & creatives (Features 1 and 2)
# ---------------------------------------------------------------------------

@app.route("/api/campaigns", methods=["POST"])
def create_campaign():
    """
    Purpose: Create an advertising campaign with targeting parameters
             (Feature 1).
    Input:   JSON body: name, advertiser, cpm_bid; optional status
             ("active" | "paused", default "active") and targeting
             {countries, device_types, site_categories}.
    Output:  201 + the stored campaign (with its generated id), or
             400 + {"error", "details": [...]} listing every problem found.
    Example: curl -X POST http://localhost:5000/api/campaigns
               -H "Content-Type: application/json"
               -d '{"name": "Diwali Sale", "advertiser": "Acme",
                    "cpm_bid": 2.5,
                    "targeting": {"countries": ["IND"],
                                  "device_types": ["mobile"]}}'
    """
    payload = request.get_json(silent=True)
    problems = validator.check_campaign(payload)
    if problems:
        return jsonify({"error": "invalid campaign", "details": problems}), 400

    targeting = payload.get("targeting", {})
    campaign = {
        "id": storage.new_id("camp"),
        "name": payload["name"].strip(),
        "advertiser": payload["advertiser"].strip(),
        "status": payload.get("status", "active"),
        "cpm_bid": round(float(payload["cpm_bid"]), 4),
        "targeting": {
            # Normalised once, here at the door, so the matcher can rely on
            # exact comparisons: countries/categories upper, devices lower.
            "countries": [c.upper() for c in targeting.get("countries", [])],
            "device_types": [d.lower() for d in targeting.get("device_types", [])],
            "site_categories": [s.upper() for s in targeting.get("site_categories", [])],
        },
    }
    storage.append_record(storage.CAMPAIGNS_FILE, campaign)
    return jsonify(campaign), 201


@app.route("/api/campaigns", methods=["GET"])
def list_campaigns():
    """
    Purpose: List all campaigns (used by the dashboard and for testing).
    Input:   None.
    Output:  200 + JSON array of campaign objects.
    Example: curl http://localhost:5000/api/campaigns
    """
    return jsonify(storage.load_json(storage.CAMPAIGNS_FILE))


@app.route("/api/creatives", methods=["POST"])
def create_creative():
    """
    Purpose: Register a creative (ad) and associate it with a campaign
             (Feature 2).
    Input:   JSON body: name, campaign_id (must exist), w, h (pixels),
             adm (the ad markup); optional adomain (advertiser domains).
    Output:  201 + the stored creative (with its generated id), or
             400 + {"error", "details": [...]}.
    Example: curl -X POST http://localhost:5000/api/creatives
               -H "Content-Type: application/json"
               -d '{"name": "Acme 300x250", "campaign_id": "camp_a1b2c3",
                    "w": 300, "h": 250,
                    "adm": "<div>Acme Shoes - 50% off!</div>"}'
    """
    payload = request.get_json(silent=True)
    campaigns = storage.load_json(storage.CAMPAIGNS_FILE)
    problems = validator.check_creative(payload, campaigns)
    if problems:
        return jsonify({"error": "invalid creative", "details": problems}), 400

    creative = {
        "id": storage.new_id("cr"),
        "campaign_id": payload["campaign_id"],
        "name": payload["name"].strip(),
        "w": payload["w"],
        "h": payload["h"],
        "adm": payload["adm"],
        "adomain": payload.get("adomain", []),
    }
    storage.append_record(storage.CREATIVES_FILE, creative)
    return jsonify(creative), 201


@app.route("/api/creatives", methods=["GET"])
def list_creatives():
    """
    Purpose: List all creatives (used by the dashboard and for testing).
    Input:   None.
    Output:  200 + JSON array of creative objects.
    Example: curl http://localhost:5000/api/creatives
    """
    return jsonify(storage.load_json(storage.CREATIVES_FILE))


# ---------------------------------------------------------------------------
# The auction (Features 3, 4 and 5)
# ---------------------------------------------------------------------------

@app.route("/openrtb/bid", methods=["POST"])
def handle_bid_request():
    """
    Purpose: The auction endpoint: accept an OpenRTB 2.x bid request and
             answer with a bid, a no-bid, or a validation error
             (Features 3, 4 and 5 end to end).
    Input:   OpenRTB 2.x BidRequest JSON (see samples/ for examples).
    Output:  200 + OpenRTB BidResponse JSON  - a campaign matched and bids
             204 + empty body                - valid request, nobody bids
             400 + {"error", "details"}      - malformed request
    Example: curl -X POST http://localhost:5000/openrtb/bid
               -H "Content-Type: application/json"
               -d @samples/bid_request_match.json
    """
    payload = request.get_json(silent=True)

    problems = validator.check_bid_request(payload)
    if problems:
        request_id = payload.get("id") if isinstance(payload, dict) else None
        tracker.log_auction("invalid", request_id, reason="; ".join(problems))
        return jsonify({"error": "invalid bid request", "details": problems}), 400

    campaigns = storage.load_json(storage.CAMPAIGNS_FILE)
    creatives = storage.load_json(storage.CREATIVES_FILE)
    matches = matcher.find_matches(campaigns, creatives, payload)

    if not matches:
        # A precise reason turns the dashboard into a debugging tool.
        reason = ("no campaigns exist yet" if not campaigns else
                  "no active campaign matched (targeting, floor, or creative size)")
        tracker.log_auction("no_bid", payload["id"], reason=reason)
        # 204 No Content is the OpenRTB-standard way to decline politely.
        return "", 204

    winner = bidding.select_winner(matches)
    bid_id = storage.new_id("bid")
    # request.host_url is this server's own address -- injected into the
    # response builder so the win-notice nurl always points back at us.
    response = bidding.build_bid_response(payload, winner, bid_id,
                                          request.host_url)
    tracker.log_auction(
        "bid",
        payload["id"],
        bid_id=bid_id,
        campaign_id=winner["campaign"]["id"],
        creative_id=winner["creative"]["id"],
        price=response["seatbid"][0]["bid"][0]["price"],
    )
    return jsonify(response), 200


@app.route("/api/log", methods=["GET"])
def auction_log():
    """
    Purpose: Return the auction flight recorder (used by the dashboard).
    Input:   None.
    Output:  200 + JSON array of bid log entries, newest first.
    Example: curl http://localhost:5000/api/log
    """
    entries = storage.load_json(storage.BID_LOG_FILE)
    return jsonify(list(reversed(entries)))


# ---------------------------------------------------------------------------
# Win notice & impressions (Feature 6)
# ---------------------------------------------------------------------------

@app.route("/win", methods=["GET"])
def win_notice():
    """
    Purpose: The win-notice endpoint (Feature 6). Every bid response's nurl
             points here; "the exchange" (you, during a demo) fires it to
             declare our bid the winner, and we record the impression.
    Input:   Query params: bid_id (required); price (optional -- the
             clearing price. If missing, or still the literal
             ${AUCTION_PRICE} macro, we fall back to our own bid price).
    Output:  200 + the impression record (idempotent: the same notice
             twice returns the same impression, stored once);
             400 if bid_id is missing; 404 if bid_id is unknown.
    Example: curl "http://localhost:5000/win?bid_id=bid_1a2b3c&price=1.87"
    """
    bid_id = request.args.get("bid_id", "").strip()
    if not bid_id:
        return jsonify({"error": "missing required query parameter 'bid_id'"}), 400

    # Query-string values are always text; turning them into a usable float
    # (or None) is an HTTP concern, so it happens here in the web layer.
    try:
        win_price = float(request.args.get("price", ""))
        if win_price < 0:
            win_price = None
    except ValueError:
        win_price = None

    impression = tracker.record_win(bid_id, win_price)
    if impression is None:
        return jsonify({"error": f"no bid with id '{bid_id}' in the bid log"}), 404
    return jsonify(impression), 200


@app.route("/api/impressions", methods=["GET"])
def list_impressions():
    """
    Purpose: Return all confirmed impressions (used by the dashboard).
    Input:   None.
    Output:  200 + JSON array of impression records, newest first.
    Example: curl http://localhost:5000/api/impressions
    """
    impressions = storage.load_json(storage.IMPRESSIONS_FILE)
    return jsonify(list(reversed(impressions)))


# All six required features are now implemented. The dashboard (Phase 5)
# consumes the GET endpoints above.


if __name__ == "__main__":
    # debug=True gives auto-reload on save and readable tracebacks.
    # This is a local educational tool, so the dev server is exactly right;
    # a production DSP would sit behind a real WSGI server instead.
    app.run(debug=True, port=8000)
