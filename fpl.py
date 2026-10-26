"""Fetch, cache and search Fantasy Premier League player data.

Kept separate from the Flask app so it can be tested without a web server.
"""

import json
import sqlite3
import time
import unicodedata
import urllib.request
from pathlib import Path

API_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
DB_PATH = Path(__file__).with_name("players.db")
MAX_AGE_SECONDS = 3 * 60 * 60  # refresh the cache when it is older than 3 hours
MAX_MATCHES = 10               # how many options to show for an ambiguous name

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS players (
    id                INTEGER PRIMARY KEY,  -- FPL player id (web_name is not unique)
    web_name          TEXT,
    first_name        TEXT,
    second_name       TEXT,
    club              TEXT,
    position          TEXT,
    now_cost          INTEGER,              -- tenths of a million: 79 means £7.9m
    total_points      INTEGER,
    goals_scored      INTEGER,
    assists           INTEGER,
    minutes           INTEGER,
    expected_goals    REAL,
    expected_assists  REAL,
    fetched_at        REAL                  -- unix time this row was downloaded
)
"""

# Letters that Unicode normalization does not split into "base letter + accent",
# so they need translating by hand. The apostrophe is dropped so "obrien" finds "O'Brien".
SPECIAL_LETTERS = str.maketrans({
    "ø": "o", "Ø": "o", "đ": "d", "Đ": "d", "ı": "i", "ł": "l", "Ł": "l",
    "æ": "ae", "Æ": "ae", "ß": "ss", "'": None, "’": None,
})


class DataUnavailable(Exception):
    """The API can't be reached and there is no cached data to fall back on."""


def fetch_from_api():
    """Download every player from the FPL API, shaped to match the players table."""
    request = urllib.request.Request(API_URL, headers={"User-Agent": "player-comp-fpl"})
    with urllib.request.urlopen(request, timeout=10) as response:
        # Decode explicitly: never rely on the default encoding (cp1252 on Windows).
        data = json.loads(response.read().decode("utf-8"))

    positions = {t["id"]: t["singular_name_short"] for t in data["element_types"]}
    clubs = {t["id"]: t["name"] for t in data["teams"]}
    now = time.time()

    players = []
    for e in data["elements"]:
        players.append({
            "id": e["id"],
            "web_name": e["web_name"],
            "first_name": e["first_name"],
            "second_name": e["second_name"],
            "club": clubs[e["team"]],
            "position": positions[e["element_type"]],
            "now_cost": e["now_cost"],
            "total_points": e["total_points"],
            "goals_scored": e["goals_scored"],
            "assists": e["assists"],
            "minutes": e["minutes"],
            # The API sends these as strings like "6.09", so convert them.
            "expected_goals": float(e["expected_goals"]),
            "expected_assists": float(e["expected_assists"]),
            "fetched_at": now,
        })
    return players


def save_players(conn, players):
    """Replace the whole table with fresh rows, in one transaction."""
    with conn:  # commits if everything succeeds, rolls back if anything fails
        conn.execute("DELETE FROM players")
        conn.executemany(
            """INSERT INTO players VALUES (
                :id, :web_name, :first_name, :second_name, :club, :position,
                :now_cost, :total_points, :goals_scored, :assists, :minutes,
                :expected_goals, :expected_assists, :fetched_at)""",
            players,
        )


def load_players():
    """Return (players, notice).

    Serves from SQLite, refreshing from the API first if the cache is missing or
    old. If the refresh fails but we have old data, `notice` explains that.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["web_name"]
    try:
        conn.execute(CREATE_TABLE)
        last_fetched = conn.execute("SELECT MAX(fetched_at) FROM players").fetchone()[0]
        notice = None

        if last_fetched is None or time.time() - last_fetched > MAX_AGE_SECONDS:
            try:
                save_players(conn, fetch_from_api())
            # OSError covers no connection, timeouts and HTTP errors;
            # ValueError/KeyError cover a response that isn't what we expect.
            except (OSError, ValueError, KeyError) as error:
                if last_fetched is None:
                    raise DataUnavailable(
                        "Couldn't reach the Fantasy Premier League API and there is "
                        "no saved data yet. Check your connection and try again."
                    ) from error
                saved_at = time.strftime("%d %b %H:%M", time.localtime(last_fetched))
                notice = f"Couldn't reach the FPL API, so this uses saved data from {saved_at}."

        rows = conn.execute("SELECT * FROM players").fetchall()
        return [dict(row) for row in rows], notice
    finally:
        conn.close()


def normalize(text):
    """Lowercase and strip accents so "Ødegaard" and "odegaard" compare equal."""
    text = text.translate(SPECIAL_LETTERS)
    # NFKD splits "é" into "e" + a separate accent mark, which we then drop.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


def search(players, query):
    """Return players matching `query`, highest FPL points first.

    An exact match on display name or full name beats partial matches, so
    "Isak" finds Isak even though other names contain "isak".
    """
    query = normalize(query)
    words = query.split()
    exact, partial = [], []
    for p in players:
        web_name = normalize(p["web_name"])
        full_name = normalize(f"{p['first_name']} {p['second_name']}")
        if query in (web_name, full_name):
            exact.append(p)
        elif all(word in f"{web_name} {full_name}" for word in words):
            partial.append(p)
    matches = exact or partial
    return sorted(matches, key=lambda p: p["total_points"], reverse=True)


def summary(p):
    """The short description of a player the front end needs."""
    return {
        "id": p["id"],
        "web_name": p["web_name"],
        "full_name": f"{p['first_name']} {p['second_name']}",
        "club": p["club"],
        "position": p["position"],
        "price": f"£{p['now_cost'] / 10:.1f}m",
    }


def resolve(players, query, player_id=None):
    """Turn what the user typed (or picked from a list) into exactly one player.

    Returns {"player": ...} on success, or {"error": ..., "matches": [...]}.
    """
    if player_id is not None:
        for p in players:
            if p["id"] == player_id:
                return {"player": p}

    matches = search(players, query)
    if not matches:
        return {"error": f'No Premier League player matches "{query}".', "matches": []}
    if len(matches) > 1:
        shown = matches[:MAX_MATCHES]
        message = f'"{query}" matches {len(matches)} players. Pick one'
        if len(matches) > len(shown):
            message += f" (showing the top {len(shown)}, or type more of the name)"
        return {"error": message + ":", "matches": [summary(p) for p in shown]}
    return {"player": matches[0]}


def per_90(count, minutes):
    """Rate per 90 minutes played, or None for a player who hasn't played."""
    if minutes == 0:
        return None
    return round(count / minutes * 90, 2)


def row(label, a, b, fmt="{}", better=None):
    """One comparison row. `better` is "higher", "lower" or None (don't compare)."""
    winner = None
    if better and a is not None and b is not None and a != b:
        a_wins = a > b if better == "higher" else a < b
        winner = "a" if a_wins else "b"
    return {
        "label": label,
        "a": "–" if a is None else fmt.format(a),
        "b": "–" if b is None else fmt.format(b),
        "better": winner,
    }


def compare(a, b):
    """Build the side-by-side rows for two players."""
    return [
        row("Club", a["club"], b["club"]),
        row("Position", a["position"], b["position"]),
        row("Goals", a["goals_scored"], b["goals_scored"], better="higher"),
        row("Assists", a["assists"], b["assists"], better="higher"),
        row("Expected goals (xG)", a["expected_goals"], b["expected_goals"], "{:.2f}", "higher"),
        row("Expected assists (xA)", a["expected_assists"], b["expected_assists"], "{:.2f}", "higher"),
        row("Minutes", a["minutes"], b["minutes"], better="higher"),
        row("Goals per 90", per_90(a["goals_scored"], a["minutes"]),
            per_90(b["goals_scored"], b["minutes"]), "{:.2f}", "higher"),
        row("Assists per 90", per_90(a["assists"], a["minutes"]),
            per_90(b["assists"], b["minutes"]), "{:.2f}", "higher"),
        row("Price", a["now_cost"] / 10, b["now_cost"] / 10, "£{:.1f}m", "lower"),
    ]
