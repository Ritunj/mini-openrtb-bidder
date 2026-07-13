"""
Purpose:
    Validate every piece of data that enters the simulator, before any
    other module is allowed to touch it.

Responsibilities:
    - check_campaign(payload): problems in a campaign-creation request
    - check_creative(payload, campaigns): problems in a creative-creation
      request, including whether the referenced campaign exists
    - check_bid_request(payload): problems in an incoming OpenRTB 2.x
      bid request (strict on required fields, typed-if-present on optional)
    - Every check returns a list of human-readable problem strings.
      An empty list means "valid". Checks never raise, never touch disk.

Dependencies:
    - None (pure Python; no Flask, no storage -- easy to test in isolation)
"""

ALLOWED_DEVICE_TYPES = {"mobile", "tablet", "desktop", "ctv"}
ALLOWED_STATUSES = {"active", "paused"}


# ---------------------------------------------------------------------------
# Small reusable checks
# ---------------------------------------------------------------------------

def _is_nonempty_string(value) -> bool:
    """True if value is a string with visible characters."""
    return isinstance(value, str) and value.strip() != ""


def _is_positive_number(value) -> bool:
    """True if value is an int/float greater than 0 (bools excluded)."""
    # In Python, True is an instance of int, so bool must be ruled out
    # explicitly or `"cpm_bid": true` would slip through as the number 1.
    return (isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0)


def _is_positive_int(value) -> bool:
    """True if value is an integer greater than 0 (bools excluded)."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_nonnegative_number(value) -> bool:
    """True if value is an int/float >= 0 (bools excluded).

    Used for bidfloor: a floor of 0 is legal (means "any price wins").
    """
    return (isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 0)


def _is_list_of_strings(value) -> bool:
    """True if value is a list containing only strings (may be empty)."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


# ---------------------------------------------------------------------------
# Campaign validation (Feature 1)
# ---------------------------------------------------------------------------

def check_campaign(payload) -> list:
    """
    Purpose: Find every problem in a campaign-creation payload.
    Input:   payload - whatever the client POSTed (may be None or non-dict).
    Output:  list of problem strings; empty list means the campaign is valid.
    Example: check_campaign({"name": "Sale", "advertiser": "Acme",
                             "cpm_bid": 2.5})  ->  []
    """
    if not isinstance(payload, dict):
        return ["request body must be a JSON object"]

    problems = []

    if not _is_nonempty_string(payload.get("name")):
        problems.append("'name' is required and must be a non-empty string")

    if not _is_nonempty_string(payload.get("advertiser")):
        problems.append("'advertiser' is required and must be a non-empty string")

    if not _is_positive_number(payload.get("cpm_bid")):
        problems.append("'cpm_bid' is required and must be a number greater than 0")

    if payload.get("status", "active") not in ALLOWED_STATUSES:
        problems.append("'status' must be one of: active, paused")

    targeting = payload.get("targeting", {})
    if not isinstance(targeting, dict):
        problems.append("'targeting' must be a JSON object")
        return problems  # cannot inspect its keys if it is not a dict

    for key in ("countries", "device_types", "site_categories"):
        if key in targeting and not _is_list_of_strings(targeting[key]):
            problems.append(f"'targeting.{key}' must be a list of strings")

    device_types = targeting.get("device_types", [])
    if _is_list_of_strings(device_types):
        unknown = {d.lower() for d in device_types} - ALLOWED_DEVICE_TYPES
        if unknown:
            problems.append(
                "'targeting.device_types' contains unknown values: "
                + ", ".join(sorted(unknown))
                + " (allowed: mobile, tablet, desktop, ctv)"
            )

    return problems


# ---------------------------------------------------------------------------
# Creative validation (Feature 2)
# ---------------------------------------------------------------------------

def check_creative(payload, campaigns: list) -> list:
    """
    Purpose: Find every problem in a creative-creation payload.
    Input:   payload - whatever the client POSTed;
             campaigns - the current list of campaigns, so the referenced
             campaign_id can be verified to exist.
    Output:  list of problem strings; empty list means the creative is valid.
    Example: check_creative({"name": "Banner", "campaign_id": "camp_a1b2c3",
                             "w": 300, "h": 250, "adm": "<div>Hi</div>"},
                            campaigns)  ->  []
    """
    if not isinstance(payload, dict):
        return ["request body must be a JSON object"]

    problems = []

    if not _is_nonempty_string(payload.get("name")):
        problems.append("'name' is required and must be a non-empty string")

    campaign_id = payload.get("campaign_id")
    if not _is_nonempty_string(campaign_id):
        problems.append("'campaign_id' is required and must be a non-empty string")
    elif not any(c.get("id") == campaign_id for c in campaigns):
        # A creative must belong to a real campaign -- this is the
        # "associate a creative with a campaign" half of Feature 2.
        problems.append(f"campaign '{campaign_id}' does not exist")

    for side in ("w", "h"):
        if not _is_positive_int(payload.get(side)):
            problems.append(f"'{side}' is required and must be a positive "
                            "integer (pixels)")

    if not _is_nonempty_string(payload.get("adm")):
        problems.append("'adm' (the ad markup) is required and must be a "
                        "non-empty string")

    if "adomain" in payload and not _is_list_of_strings(payload["adomain"]):
        problems.append("'adomain' must be a list of domain strings")

    return problems


# ---------------------------------------------------------------------------
# OpenRTB bid request validation (used by POST /openrtb/bid)
# ---------------------------------------------------------------------------

def check_bid_request(payload) -> list:
    """
    Purpose: Find every problem in an incoming OpenRTB 2.x bid request.
             Required fields are checked strictly. Optional objects
             (banner, site, device, geo) are type-checked only if present,
             and unknown fields (user, tmax, cur, ext, ...) are ignored --
             a bidder should never reject fields it does not consume.
    Input:   payload - whatever the exchange POSTed to /openrtb/bid.
    Output:  list of problem strings; empty list means the request is valid.
    Example: check_bid_request({"id": "req-1",
                                "imp": [{"id": "1",
                                         "banner": {"w": 300, "h": 250}}]})
             -> []
    """
    if not isinstance(payload, dict):
        return ["request body must be a JSON object"]

    problems = []

    if not _is_nonempty_string(payload.get("id")):
        problems.append("'id' is required and must be a non-empty string "
                        "(the exchange's auction id)")

    imp = payload.get("imp")
    if not isinstance(imp, list) or len(imp) == 0:
        problems.append("'imp' is required and must be a non-empty array "
                        "of impression objects")
    else:
        # Documented simplification: this simulator evaluates imp[0] only.
        problems.extend(_check_impression(imp[0]))

    problems.extend(_check_context(payload))
    return problems


def _check_impression(imp) -> list:
    """Checks for imp[0], the impression this simulator bids on."""
    if not isinstance(imp, dict):
        return ["'imp[0]' must be a JSON object"]

    problems = []

    if not _is_nonempty_string(imp.get("id")):
        problems.append("'imp[0].id' is required and must be a non-empty string")

    # NOTE: a request with NO banner object is still valid OpenRTB -- it may
    # be a video or native impression. We are a banner-only bidder, so such a
    # request will simply find no matching creative and end as a 204 no-bid.
    # That is the spec-correct behaviour; a 400 would wrongly call a valid
    # request "malformed". A banner that IS present must be usable, though:
    banner = imp.get("banner")
    if banner is not None:
        if not isinstance(banner, dict):
            problems.append("'imp[0].banner' must be a JSON object")
        else:
            for side in ("w", "h"):
                if not _is_positive_int(banner.get(side)):
                    problems.append(f"'imp[0].banner.{side}' is required and "
                                    "must be a positive integer (pixels)")

    if "bidfloor" in imp and not _is_nonnegative_number(imp["bidfloor"]):
        problems.append("'imp[0].bidfloor' must be a number >= 0 (a CPM price)")

    return problems


def _check_context(payload) -> list:
    """Type-checks the optional site / device / geo objects, if present.

    The rule: any field the matcher will READ must be guaranteed well-typed
    once validation passes, so the matcher needs no defensive code at all.
    """
    problems = []

    site = payload.get("site")
    if site is not None:
        if not isinstance(site, dict):
            problems.append("'site' must be a JSON object")
        elif "cat" in site and not _is_list_of_strings(site["cat"]):
            problems.append("'site.cat' must be a list of IAB category strings")

    device = payload.get("device")
    if device is not None:
        if not isinstance(device, dict):
            problems.append("'device' must be a JSON object")
        else:
            devicetype = device.get("devicetype")
            if devicetype is not None and (not isinstance(devicetype, int)
                                           or isinstance(devicetype, bool)):
                problems.append("'device.devicetype' must be an integer "
                                "(OpenRTB device type code)")

            geo = device.get("geo")
            if geo is not None:
                if not isinstance(geo, dict):
                    problems.append("'device.geo' must be a JSON object")
                elif "country" in geo and not isinstance(geo["country"], str):
                    problems.append("'device.geo.country' must be a string "
                                    '(ISO-3166-1 alpha-3, e.g. "IND")')

    return problems
