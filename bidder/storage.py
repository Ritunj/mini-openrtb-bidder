"""
Purpose:
    The one and only module that reads and writes the JSON files in data/.
    Plays the role that Redis/PostgreSQL play in a production DSP.

Responsibilities:
    - Load and save each data file (campaigns, creatives, bid log, impressions)
    - Append records, optionally capping how many are kept (bid log)
    - Generate short unique ids for new records
    - Keep every other module free of file-handling code

Dependencies:
    - json, pathlib, uuid (standard library only)
"""

import json
import uuid
from pathlib import Path

# data/ sits next to app.py, one level above this file (bidder/storage.py).
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

CAMPAIGNS_FILE = DATA_DIR / "campaigns.json"
CREATIVES_FILE = DATA_DIR / "creatives.json"
BID_LOG_FILE = DATA_DIR / "bid_log.json"
IMPRESSIONS_FILE = DATA_DIR / "impressions.json"

# The bid log powers the dashboard and win-notice lookups. It does not need
# to remember every auction ever, so only the most recent entries are kept.
BID_LOG_MAX_ENTRIES = 100


def load_json(file_path: Path) -> list:
    """
    Purpose: Read one data file and return its contents as a Python list.
    Input:   file_path - one of this module's *_FILE constants (or any Path).
    Output:  list of dicts; an empty list if the file is missing, empty,
             or not valid JSON.
    Example: campaigns = load_json(CAMPAIGNS_FILE)
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # A missing or corrupted file behaves like an empty store, so a fresh
        # clone (or a bad manual edit) degrades gracefully instead of crashing.
        return []
    # Guard against a file someone edited into a non-list shape.
    return data if isinstance(data, list) else []


def save_json(file_path: Path, records: list) -> None:
    """
    Purpose: Write a full list of records to one data file.
    Input:   file_path - destination file; records - list of dicts.
    Output:  None. The file now contains exactly `records`, pretty-printed.
    Example: save_json(CAMPAIGNS_FILE, campaigns)
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        # indent=2 keeps the "database" human-readable: you can open any
        # data file in an editor and see exactly what the simulator knows.
        json.dump(records, f, indent=2)


def append_record(file_path: Path, record: dict,
                  max_entries: int | None = None) -> dict:
    """
    Purpose: Add one record to a data file (load -> append -> save).
    Input:   file_path - destination file; record - the dict to add;
             max_entries - if set, only the most recent max_entries
             records are kept (used for the bid log).
    Output:  The record that was appended.
    Example: append_record(IMPRESSIONS_FILE, impression)
             append_record(BID_LOG_FILE, entry, max_entries=BID_LOG_MAX_ENTRIES)
    """
    records = load_json(file_path)
    records.append(record)
    if max_entries is not None and len(records) > max_entries:
        records = records[-max_entries:]
    save_json(file_path, records)
    return record


def new_id(prefix: str) -> str:
    """
    Purpose: Generate a short unique id such as "camp_a3f2c1".
    Input:   prefix - "camp", "cr", or "bid".
    Output:  prefix + "_" + the first 6 hex characters of a random UUID.
    Example: new_id("camp")  ->  "camp_9b1c4e"
    """
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


def find_by_id(records: list, record_id: str) -> dict | None:
    """
    Purpose: Find one record in a list by its "id" field.
    Input:   records - list of dicts; record_id - the id to look for.
    Output:  The matching dict, or None if no record has that id.
    Example: campaign = find_by_id(load_json(CAMPAIGNS_FILE), "camp_9b1c4e")
    """
    for record in records:
        if record.get("id") == record_id:
            return record
    return None
