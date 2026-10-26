"""Flask web app: one page, one JSON endpoint."""

from flask import Flask, jsonify, render_template, request

import fpl

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/compare")
def compare():
    body = request.get_json(silent=True) or {}
    name_a = str(body.get("a", "")).strip()
    name_b = str(body.get("b", "")).strip()
    if not name_a or not name_b:
        return jsonify(error="Enter a player name in both boxes."), 400

    try:
        players, notice = fpl.load_players()
    except fpl.DataUnavailable as error:
        return jsonify(error=str(error)), 503

    # a_id / b_id are set when the user picked a player from a "did you mean" list.
    a = fpl.resolve(players, name_a, body.get("a_id"))
    b = fpl.resolve(players, name_b, body.get("b_id"))

    rows = None
    if "player" in a and "player" in b:
        rows = fpl.compare(a["player"], b["player"])

    # Send only what the page displays, not the whole database row.
    for side in (a, b):
        if "player" in side:
            side["player"] = fpl.summary(side["player"])

    return jsonify(notice=notice, a=a, b=b, rows=rows)


@app.errorhandler(500)
def server_error(error):
    # Anything unexpected becomes a plain message, never a stack trace.
    return jsonify(error="Something went wrong on the server. Please try again."), 500


if __name__ == "__main__":
    app.run()
