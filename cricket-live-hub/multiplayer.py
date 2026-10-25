"""
Online multiplayer for Cricket League 3D, stored in a SQLite .db file
=====================================================================
Everything multiplayer lives in cricket_multiplayer.db:

* users / sessions - accounts (username + salted PBKDF2 password hash) and sign-in tokens
* rooms / room_players - match rooms with 5-letter codes, and who is in each one
* events - the messages the two players' games send each other (every delivery and result)
* seasons - each signed-in player's IPL season in progress (fixtures, results, playoffs), saved after every match

The game sends requests through a small bridge component on the Cricket Live Hub page
(templates/index.html), and streamlit_app.py passes each one to handle(). It all runs inside
the Streamlit app, so anyone who can open the app, anywhere, can create or join a room.
"""

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "cricket_multiplayer.db"
TEAMS = {"CSK", "MI", "RCB", "KKR", "DC", "PBKS", "RR", "SRH", "GT", "LSG"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
STALE_AFTER = 25          # seconds without polling before a player counts as disconnected
MAX_PAYLOAD = 20_000      # bytes per game message

SCHEMA = """
create table if not exists users (
    id       integer primary key autoincrement,
    username text not null unique collate nocase,
    pw_hash  blob not null,
    salt     blob not null,
    team     text not null default 'MI',
    wins     integer not null default 0,
    losses   integer not null default 0,
    created  real not null
);
create table if not exists sessions (
    token   text primary key,
    user_id integer not null references users(id) on delete cascade,
    created real not null
);
create table if not exists rooms (
    code    text primary key,
    host_id integer not null,
    overs   integer not null,
    wkts    integer not null,
    closed  integer not null default 0,
    created real not null,
    updated real not null
);
create table if not exists room_players (
    code      text not null references rooms(code) on delete cascade,
    user_id   integer not null,
    name      text not null,
    team      text not null,
    last_seen real not null,
    primary key (code, user_id)
);
create table if not exists events (
    id      integer primary key autoincrement,
    code    text not null,
    sender  integer not null,
    payload text not null,
    req_id  text unique,
    created real not null
);
create index if not exists events_by_room on events (code, id);
create table if not exists seasons (
    user_id integer primary key references users(id) on delete cascade,
    data    text not null,
    updated real not null
);
"""


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


_ready = False


def init_db():
    global _ready
    if _ready:
        return
    with closing(connect()) as conn:
        conn.execute("pragma journal_mode = wal")  # lets many players read while one writes
        conn.executescript(SCHEMA)
    _ready = True


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)


def _profile(row):
    return {"id": row["id"], "username": row["username"], "team": row["team"],
            "wins": row["wins"], "losses": row["losses"]}


def _user_row(conn, user_id):
    return conn.execute("select * from users where id = ?", (user_id,)).fetchone()


def _auth(conn, data):
    token = data.get("token")
    row = conn.execute("select u.* from sessions s join users u on u.id = s.user_id where s.token = ?",
                       (token,)).fetchone() if token else None
    if not row:
        raise ApiError(401, "Please sign in again.")
    return row


def _new_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    conn.execute("insert into sessions (token, user_id, created) values (?, ?, ?)", (token, user_id, time.time()))
    return {"token": token, "profile": _profile(_user_row(conn, user_id))}


def op_signup(conn, d, rid):
    username, password = str(d.get("username") or "").strip(), str(d.get("password") or "")
    if not USERNAME_RE.match(username):
        raise ApiError(400, "Usernames are 3-16 letters, numbers or _.")
    if len(password) < 6:
        raise ApiError(400, "Passwords need at least 6 characters.")
    if conn.execute("select 1 from users where username = ?", (username,)).fetchone():
        raise ApiError(409, "That username is taken. Try another one.")
    salt = secrets.token_bytes(16)
    cur = conn.execute("insert into users (username, pw_hash, salt, created) values (?, ?, ?, ?)",
                       (username, _hash(password, salt), salt, time.time()))
    return _new_session(conn, cur.lastrowid)


def op_login(conn, d, rid):
    row = conn.execute("select * from users where username = ?", (str(d.get("username") or "").strip(),)).fetchone()
    if not row or not hmac.compare_digest(row["pw_hash"], _hash(str(d.get("password") or ""), row["salt"])):
        raise ApiError(401, "Wrong username or password.")
    return _new_session(conn, row["id"])


def op_me(conn, d, rid):
    return {"profile": _profile(_auth(conn, d))}


def op_logout(conn, d, rid):
    conn.execute("delete from sessions where token = ?", (d.get("token"),))
    return {"ok": True}


def op_team(conn, d, rid):
    user, team = _auth(conn, d), d.get("team")
    if team not in TEAMS:
        raise ApiError(400, "Unknown team.")
    conn.execute("update users set team = ? where id = ?", (team, user["id"]))
    return {"ok": True}


def op_result(conn, d, rid):
    user = _auth(conn, d)
    column = "wins" if d.get("won") else "losses"
    conn.execute(f"update users set {column} = {column} + 1 where id = ?", (user["id"],))
    return {"profile": _profile(_user_row(conn, user["id"]))}


# --------------------------------------------------------------------------- #
# Rooms
# --------------------------------------------------------------------------- #
def _code(value):
    return str(value or "").upper().strip()


def _snapshot(conn, code):
    room = conn.execute("select * from rooms where code = ?", (code,)).fetchone()
    players = conn.execute("select user_id, name, team from room_players where code = ? order by rowid", (code,)).fetchall()
    return {"t": "room", "code": code, "overs": room["overs"], "wkts": room["wkts"],
            "players": [{"id": p["user_id"], "name": p["name"], "team": p["team"], "host": p["user_id"] == room["host_id"]}
                        for p in players]}


def _event(conn, code, sender, payload, req_id=None):
    now = time.time()
    conn.execute("insert or ignore into events (code, sender, payload, req_id, created) values (?, ?, ?, ?, ?)",
                 (code, sender, json.dumps(payload), req_id, now))
    conn.execute("update rooms set updated = ? where code = ?", (now, code))


def _joined(conn, code):
    since = conn.execute("select coalesce(max(id), 0) from events where code = ?", (code,)).fetchone()[0]
    return {"code": code, "room": _snapshot(conn, code), "since": since}


def _open_room(conn, code):
    room = conn.execute("select * from rooms where code = ? and closed = 0", (_code(code),)).fetchone()
    if not room:
        raise ApiError(404, "No room found with that code.")
    return room


def _in_room(conn, code, user_id):
    return conn.execute("select 1 from room_players where code = ? and user_id = ?", (code, user_id)).fetchone() is not None


def _add_player(conn, code, user):
    conn.execute("insert into room_players (code, user_id, name, team, last_seen) values (?, ?, ?, ?, ?)",
                 (code, user["id"], user["username"], user["team"], time.time()))
    _event(conn, code, 0, _snapshot(conn, code))


def _remove_player(conn, room, user_id):
    code = room["code"]
    conn.execute("delete from room_players where code = ? and user_id = ?", (code, user_id))
    _event(conn, code, user_id, {"t": "leave"})
    _event(conn, code, 0, _snapshot(conn, code))
    left = conn.execute("select count(*) from room_players where code = ?", (code,)).fetchone()[0]
    if user_id == room["host_id"] or not left:
        conn.execute("update rooms set closed = 1 where code = ?", (code,))


def _cleanup(conn):
    """Forget rooms nobody has used for an hour, and old messages."""
    now = time.time()
    conn.execute("delete from rooms where updated < ?", (now - 3600,))
    conn.execute("delete from events where created < ?", (now - 2 * 3600,))


def op_room_create(conn, d, rid):
    user = _auth(conn, d)
    _cleanup(conn)
    code = "".join(secrets.choice(CODE_CHARS) for _ in range(5))
    while conn.execute("select 1 from rooms where code = ?", (code,)).fetchone():
        code = "".join(secrets.choice(CODE_CHARS) for _ in range(5))
    overs = max(1, min(50, int(d.get("overs") or 2)))
    wkts = max(1, min(10, int(d.get("wkts") or 3)))
    now = time.time()
    conn.execute("insert into rooms (code, host_id, overs, wkts, created, updated) values (?, ?, ?, ?, ?, ?)",
                 (code, user["id"], overs, wkts, now, now))
    _add_player(conn, code, user)
    return _joined(conn, code)


def op_room_join(conn, d, rid):
    user, room = _auth(conn, d), _open_room(conn, d.get("code"))
    if not _in_room(conn, room["code"], user["id"]):
        if conn.execute("select count(*) from room_players where code = ?", (room["code"],)).fetchone()[0] >= 2:
            raise ApiError(409, "That room is already full.")
        _add_player(conn, room["code"], user)
    return _joined(conn, room["code"])


def op_room_leave(conn, d, rid):
    user = _auth(conn, d)
    room = conn.execute("select * from rooms where code = ?", (_code(d.get("code")),)).fetchone()
    if room and _in_room(conn, room["code"], user["id"]):
        _remove_player(conn, room, user["id"])
    return {"ok": True}


def op_room_team(conn, d, rid):
    user, room, team = _auth(conn, d), _open_room(conn, d.get("code")), d.get("team")
    if team not in TEAMS:
        raise ApiError(400, "Unknown team.")
    if not _in_room(conn, room["code"], user["id"]):
        raise ApiError(403, "You're not in this room.")
    conn.execute("update room_players set team = ? where code = ? and user_id = ?", (team, room["code"], user["id"]))
    conn.execute("update users set team = ? where id = ?", (team, user["id"]))
    _event(conn, room["code"], 0, _snapshot(conn, room["code"]))
    return {"ok": True}


def op_send(conn, d, rid):
    user, room = _auth(conn, d), _open_room(conn, d.get("code"))
    if not _in_room(conn, room["code"], user["id"]):
        raise ApiError(403, "You're not in this room.")
    if len(json.dumps(d.get("payload"))) > MAX_PAYLOAD:
        raise ApiError(413, "Message too large.")
    _event(conn, room["code"], user["id"], d.get("payload"), rid)
    return {"ok": True}


def op_poll(conn, d, rid):
    user, code = _auth(conn, d), _code(d.get("code"))
    room = conn.execute("select * from rooms where code = ?", (code,)).fetchone()
    if not room:
        raise ApiError(404, "This room has closed.")
    now = time.time()
    conn.execute("update room_players set last_seen = ? where code = ? and user_id = ?", (now, code, user["id"]))
    if not room["closed"]:  # drop players whose game stopped checking in
        for p in conn.execute("select user_id from room_players where code = ? and last_seen < ?",
                              (code, now - STALE_AFTER)).fetchall():
            _remove_player(conn, room, p["user_id"])
            room = conn.execute("select * from rooms where code = ?", (code,)).fetchone()
    rows = conn.execute("select id, sender, payload from events where code = ? and id > ? and sender != ? order by id limit 200",
                        (code, int(d.get("since") or 0), user["id"])).fetchall()
    events = [{"id": r["id"], "from": r["sender"], "payload": json.loads(r["payload"])} for r in rows]
    if not events and (room["closed"] or not _in_room(conn, code, user["id"])):
        raise ApiError(404, "This room has closed.")
    return {"events": events}


# --------------------------------------------------------------------------- #
# IPL season mode (signed-in players only): one saved season per account
# --------------------------------------------------------------------------- #
MAX_SEASON = 200_000  # bytes; a full 74-match season is about 15 KB


def op_season_load(conn, d, rid):
    user = _auth(conn, d)
    row = conn.execute("select data from seasons where user_id = ?", (user["id"],)).fetchone()
    return {"season": json.loads(row["data"]) if row else None}


def op_season_save(conn, d, rid):
    user, season = _auth(conn, d), d.get("season")
    if not isinstance(season, dict) or season.get("team") not in TEAMS or not isinstance(season.get("fixtures"), list):
        raise ApiError(400, "That season data isn't valid.")
    data = json.dumps(season)
    if len(data) > MAX_SEASON:
        raise ApiError(413, "Season data too large.")
    conn.execute("insert into seasons (user_id, data, updated) values (?, ?, ?) "
                 "on conflict(user_id) do update set data = excluded.data, updated = excluded.updated",
                 (user["id"], data, time.time()))
    return {"ok": True}


def op_season_reset(conn, d, rid):
    user = _auth(conn, d)
    conn.execute("delete from seasons where user_id = ?", (user["id"],))
    return {"ok": True}


OPS = {
    "signup": op_signup, "login": op_login, "me": op_me, "logout": op_logout, "team": op_team, "result": op_result,
    "room_create": op_room_create, "room_join": op_room_join, "room_leave": op_room_leave,
    "room_team": op_room_team, "send": op_send, "poll": op_poll,
    "season_load": op_season_load, "season_save": op_season_save, "season_reset": op_season_reset,
}


def handle(op, data, req_id=None):
    """Run one request from the game and return a JSON-friendly reply (errors come back as {"error": ...})."""
    try:
        init_db()
        fn = OPS.get(op)
        if not fn:
            raise ApiError(400, "Unknown request.")
        with closing(connect()) as conn:
            conn.execute("begin immediate")  # one short write transaction per request
            try:
                result = fn(conn, data if isinstance(data, dict) else {}, req_id)
                conn.execute("commit")
                return result
            except BaseException:
                conn.execute("rollback")
                raise
    except ApiError as e:
        return {"error": e.message, "status": e.status}
    except Exception:
        return {"error": "Something went wrong with online play. Try again.", "status": 500}
