# Premier League player comparison

A small Flask web app that compares two Premier League footballers side by side.
Type two names, press **Compare**, and you get one row per stat with the better
value highlighted in green:

club · position · goals · assists · expected goals (xG) · expected assists (xA) ·
minutes · goals per 90 · assists per 90 · price

Higher is better for every stat except price, where cheaper wins.

**Premier League only.** The data comes from the Fantasy Premier League game, so
players in other leagues aren't in it, and neither are players who have left the PL.

## Running it

You need Python 3.9 or newer.

```
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000.

The first comparison downloads the player data (about 1.8 MB) and saves it to
`players.db`. Later comparisons read from that file until it is more than three
hours old.

## The data source

Everything comes from one endpoint:

```
GET https://fantasy.premierleague.com/api/bootstrap-static/
```

This is the public JSON feed the official Fantasy Premier League website
loads in your browser. That's why it needs no API key, account or sign-up: it
has to be readable by anyone who visits the site. One request returns every
player, team and position in the game.

A few quirks the code handles:

- `now_cost` is in tenths of a million, so `79` means £7.9m.
- `expected_goals` and `expected_assists` come back as strings like `"6.09"`, so
  they are converted to numbers. `form`, `points_per_game` and
  `selected_by_percent` are strings too, but this app doesn't use them.
- `web_name` (the short display name) is not unique. There are two "Palmer"s, two
  "James"es and two "Martinez"es, so everything is keyed on the player `id`.
- Position and club come back as ids that are looked up in `element_types` and `teams`.

It's an unofficial, undocumented API, so it could change without warning.

## How it works

| File | What it does |
| --- | --- |
| `app.py` | Flask: serves the page (`GET /`) and the comparison endpoint (`POST /api/compare`) |
| `fpl.py` | Fetching from the API, the SQLite cache, name search and building the comparison rows |
| `templates/index.html` | The page, with a short vanilla JS script that calls the endpoint and draws the table |
| `static/style.css` | Plain CSS |

The fetch, cache and search logic lives in `fpl.py`, separate from Flask, so you
can test it without running a server.

**Cache.** SQLite has one table, `players`, with one row per player. Each row
stores the time it was downloaded (`fetched_at`). When a request comes in and the
newest row is more than three hours old, the table is replaced from the API in a
single transaction. If the API can't be reached:

- with saved data: the app uses it and shows a yellow notice saying how old it is;
- with no saved data: it shows an error asking you to check your connection.

**Name search** is forgiving:

- Case and accents are ignored. `odegaard` finds Ødegaard, `kadioglu` finds
  Kadıoğlu, `gross` finds Groß and `oriley` finds O'Riley. Letters like `ø`, `ı`
  and `ß` don't lose their accent through Unicode normalization, so they're
  mapped by hand.
- Partial names work, and words can be in any order (`palmer cole`).
- An exact match on display name or full name beats a partial one, so `isak`
  finds Isak rather than every name containing "isak".
- If several players still match, the app lists them (best FPL points first) and
  you click the one you meant. It never guesses.

**Encoding.** The page declares `<meta charset="utf-8">` and Flask sends
`charset=utf-8`. The API response is decoded as UTF-8 explicitly instead of
relying on Python's default, which is cp1252 on Windows and would garble
accented names.

**Per-90 stats** are `count / minutes × 90`. A player with 0 minutes shows "–"
rather than dividing by zero. Players with very few minutes can have extreme
per-90 numbers, so check the Minutes row.

## Example comparisons

These numbers are from 26 October 2026 and will change week to week.

**`haaland` vs `isak`**: Haaland wins every attacking row (9 goals and 6.09 xG,
against 6 and 4.27). Isak wins on price, at £9.0m against £15.7m.

**`odegaard` vs `palmer`**: "palmer" matches Cole Palmer (Chelsea) and Alex
Palmer (Ipswich goalkeeper), so the app asks which one you mean. Choose Cole and
the result is a real split. Both have 2 goals. Ødegaard has the higher xG and xA
and costs £3m less. Palmer has all 4 of the assists.

**`mbeumo` vs `cherki`**: both have 4 goals, but in very different ways. Mbeumo's
4.22 xG over 720 minutes says he has been getting chances. Cherki has played
437 minutes, so his goals and assists per 90 are much higher.

To see the "pick one" list for both boxes at once, try `martinez` vs `james`.
