"""
Purpose:
    Turn the matcher's output into a single OpenRTB 2.x bid response:
    pick the winning campaign, set the price, assemble the response dict.

Responsibilities:
    - select_winner(matches): the DSP's internal auction. Among all
      matching campaigns, the highest cpm_bid wins; ties go to the first
      one in the list (the oldest campaign), so results are deterministic.
    - build_bid_response(...): assemble a spec-compliant BidResponse,
      including the win-notice nurl with the ${AUCTION_PRICE} macro.

Dependencies:
    - None at all (pure Python). The bid id and the server's own address
      are passed IN as parameters ("dependency injection"), which keeps
      this module deterministic and trivial to test.
"""


def select_winner(matches: list):
    """
    Purpose: Decide which matching campaign gets to bid -- our internal
             auction. A production DSP ranks by predicted value (pCTR x
             goal value, pacing, ...); we rank by configured CPM. Same
             slot in the pipeline, one line of logic.
    Input:   matches - the [{"campaign", "creative"}] list from
             matcher.find_matches(). May be empty.
    Output:  The winning {"campaign", "creative"} pair, or None if the
             list is empty (the caller turns None into a 204 no-bid).
    Example: select_winner(matches) -> {"campaign": {...}, "creative": {...}}
    """
    if not matches:
        return None
    # max() keeps the FIRST item on ties, so equal-CPM campaigns resolve
    # to the earliest-created one -- deterministic and easy to explain.
    return max(matches, key=lambda match: match["campaign"]["cpm_bid"])


def build_bid_response(bid_request: dict, match: dict, bid_id: str,
                       host_url: str) -> dict:
    """
    Purpose: Assemble the OpenRTB 2.x bid response for one winning match.
    Input:   bid_request - the validated incoming request (its id is echoed
             back; its imp[0].id is referenced);
             match - the winning {"campaign", "creative"} pair;
             bid_id - a fresh unique id for this bid (from storage.new_id);
             host_url - this server's own base URL, e.g.
             "http://localhost:5000/", used to build the win-notice nurl.
    Output:  dict shaped exactly like an OpenRTB 2.x BidResponse. The
             caller is responsible for JSON-serialising it.
    Example: build_bid_response(request, match, "bid_1a2b3c",
                                "http://localhost:5000/")
    """
    campaign = match["campaign"]
    creative = match["creative"]
    impression = bid_request["imp"][0]

    # The ${AUCTION_PRICE} text is NOT for us to fill in. It is a literal
    # placeholder defined by the OpenRTB spec: the EXCHANGE substitutes the
    # final clearing price when it fires this URL on a win. In a second-price
    # auction that clearing price can be lower than the price we offer below.
    win_notice_url = (host_url.rstrip("/")
                      + "/win?bid_id=" + bid_id
                      + "&price=${AUCTION_PRICE}")

    return {
        "id": bid_request["id"],          # must echo the request id back
        "cur": "USD",
        "seatbid": [
            {
                "bid": [
                    {
                        "id": bid_id,
                        "impid": impression["id"],
                        "price": round(float(campaign["cpm_bid"]), 4),
                        "adm": creative["adm"],
                        "crid": creative["id"],
                        "adomain": creative.get("adomain", []),
                        "w": creative["w"],
                        "h": creative["h"],
                        "nurl": win_notice_url,
                    }
                ]
            }
        ],
    }
