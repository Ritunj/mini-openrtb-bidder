"""
Purpose:
    Rule-based campaign matching: decide which active campaigns are allowed
    (targeting) and able (creative size, bid floor) to bid on a request.

Responsibilities:
    - extract_signals(bid_request): flatten the nested OpenRTB request into
      the six flat values the rules compare against
    - find_matches(campaigns, creatives, bid_request): apply the rules to
      every campaign and return [{"campaign": ..., "creative": ...}] pairs
    - Rules, in fail-fast order (cheapest checks first):
        1. status is "active"
        2. geo      - request country in targeting.countries
        3. device   - mapped device type in targeting.device_types
        4. context  - site categories overlap targeting.site_categories
        5. price    - campaign cpm_bid >= impression bidfloor
        6. creative - campaign owns a creative exactly matching banner w x h
      For rules 2-4 an empty targeting list means "no restriction".

Dependencies:
    - None (pure Python; relies on validator.check_bid_request having
      guaranteed the types of every field read here)
"""

# OpenRTB 2.x device type codes (BidRequest.device.devicetype), grouped into
# the four names campaigns can target. Grouping 1 ("Mobile/Tablet") under
# "mobile" and 6/7 (connected device / set-top box) under "ctv" is a
# documented simplification of the spec's finer categories.
DEVICE_TYPE_NAMES = {
    1: "mobile",   # Mobile/Tablet (general)
    2: "desktop",  # Personal Computer
    3: "ctv",      # Connected TV
    4: "mobile",   # Phone
    5: "tablet",   # Tablet
    6: "ctv",      # Connected Device
    7: "ctv",      # Set Top Box
}


def extract_signals(bid_request: dict) -> dict:
    """
    Purpose: Flatten the nested OpenRTB request into the flat values the
             matching rules compare against. Done ONCE per auction, so the
             per-campaign rule checks stay trivial.
    Input:   bid_request - a dict that already passed check_bid_request().
    Output:  dict with keys: country, device_type, site_categories,
             banner_w, banner_h, bidfloor. Missing signals become
             None / [] / 0.0.
    Example: extract_signals({"id": "r", "imp": [{"id": "1",
                 "banner": {"w": 300, "h": 250}}],
                 "device": {"devicetype": 4, "geo": {"country": "IND"}}})
             -> {"country": "IND", "device_type": "mobile", ...}
    """
    imp = bid_request["imp"][0]           # documented: first impression only
    banner = imp.get("banner") or {}
    device = bid_request.get("device") or {}
    geo = device.get("geo") or {}
    site = bid_request.get("site") or {}

    country = geo.get("country")
    if country is not None:
        country = country.upper()         # same normalisation as campaigns

    return {
        "country": country,                                        # "IND" | None
        "device_type": DEVICE_TYPE_NAMES.get(device.get("devicetype")),
        "site_categories": [c.upper() for c in site.get("cat", [])],
        "banner_w": banner.get("w"),                               # int | None
        "banner_h": banner.get("h"),
        "bidfloor": float(imp.get("bidfloor", 0.0)),
    }


def find_matches(campaigns: list, creatives: list, bid_request: dict) -> list:
    """
    Purpose: Evaluate every campaign against one bid request (Feature 4).
    Input:   campaigns, creatives - current lists from storage;
             bid_request - a dict that already passed check_bid_request().
    Output:  list of {"campaign": <campaign>, "creative": <creative>} for
             every campaign that passes all six rules. Empty list = no-bid.
    Example: find_matches(campaigns, creatives, request)
             -> [{"campaign": {...}, "creative": {...}}]
    """
    signals = extract_signals(bid_request)

    matches = []
    for campaign in campaigns:
        creative = _match_one(campaign, creatives, signals)
        if creative is not None:
            matches.append({"campaign": campaign, "creative": creative})
    return matches


def _match_one(campaign: dict, creatives: list, signals: dict):
    """Apply the six rules to one campaign.

    Returns the creative to serve if every rule passes, else None.
    """
    # Rule 1 -- only active campaigns may bid.
    if campaign.get("status") != "active":
        return None

    targeting = campaign.get("targeting", {})

    # Rules 2-4 -- targeting. An empty list means "no restriction"; a missing
    # signal (e.g. request has no country) can never satisfy a restriction,
    # because the advertiser's targeting is a promise we must not break.
    if not _rule_allows(targeting.get("countries", []), signals["country"]):
        return None
    if not _rule_allows(targeting.get("device_types", []), signals["device_type"]):
        return None
    if not _lists_overlap(targeting.get("site_categories", []),
                          signals["site_categories"]):
        return None

    # Rule 5 -- our bid must clear the impression's floor price.
    if float(campaign.get("cpm_bid", 0.0)) < signals["bidfloor"]:
        return None

    # Rule 6 (last because it scans the creatives list) -- the campaign must
    # own a creative that exactly fits the requested banner slot.
    return _find_creative(campaign.get("id"), creatives,
                          signals["banner_w"], signals["banner_h"])


def _rule_allows(allowed_values: list, actual_value) -> bool:
    """One targeting rule: empty allowed-list = no restriction.

    If a restriction exists, the actual value must be in the list; a missing
    (None) value therefore fails automatically.
    """
    if not allowed_values:
        return True
    return actual_value in allowed_values


def _lists_overlap(allowed_values: list, actual_values: list) -> bool:
    """Category rule: no restriction, or at least one category in common."""
    if not allowed_values:
        return True
    return any(value in allowed_values for value in actual_values)


def _find_creative(campaign_id: str, creatives: list, w, h):
    """Return the first creative of this campaign matching w x h, else None.

    If the request had no banner (w/h are None), nothing can match --
    which is exactly how a video request becomes a clean 204 no-bid.
    """
    for creative in creatives:
        if (creative.get("campaign_id") == campaign_id
                and creative.get("w") == w
                and creative.get("h") == h):
            return creative
    return None
