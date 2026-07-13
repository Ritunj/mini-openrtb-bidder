"""
Purpose:
    The bidder package: all business logic of the Mini OpenRTB Bidder Simulator.

Responsibilities:
    - validator.py : check incoming OpenRTB bid requests
    - matcher.py   : match active campaigns against a bid request
    - bidding.py   : pick the winning campaign, price it, build the response
    - tracker.py   : handle win notices and record impressions
    - storage.py   : read/write the JSON files in data/ (only module touching disk)

Dependencies:
    - Python standard library only (no Flask imports in this package, by design)
"""
