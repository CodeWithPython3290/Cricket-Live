"""
Cricket League 3D - online game server
======================================
A small, self-contained server for playing Cricket League 3D against friends on
other computers. It uses only Python's standard library:

* accounts (username + password, salted PBKDF2 hashes) stored in SQLite (game_data.db)
* match rooms with 5-letter codes, kept in memory
* relays each delivery and result between the two players (HTTP long-polling)
* serves the game itself at http://<this-computer>:8765/

Run it on its own:   python game_server.py          (add --port 9000 to change the port)
Or run the Streamlit app, which starts it automatically in the background.
Friends on the same Wi-Fi open http://<your-computer's-IP>:8765 to play.
"""

import argparse
import hashlib
import hmac
import json
import re
import secrets
import socket
import sqlite3
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "game_data.db"
GAME_FILE = HERE / "templates" / "cricket_league_3d.html"
DEFAULT_PORT = 8765

TEAMS = {"CSK", "MI", "RCB", "KKR", "DC", "PBKS", "RR", "SRH", "GT", "LSG"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
POLL_WAIT = 20      # seconds a poll request waits for new messages
STALE_AFTER = 40    # seconds without polling before a player counts as disconnected
MAX_BODY = 64 * 1024


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


# --------------------------------------------------------------------------- #
# Accounts (SQLite)
# --------------------------------------------------------------------------- #
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(connect()) as conn, conn:
        conn.executescript("""
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
        """)


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)


def profile(row):
    return {"id": row["id"], "username": row["username"], "team": row["team"],
            "wins": row["wins"], "losses": row["losses"]}


def get_user(user_id):
    with closing(connect()) as conn:
        return conn.execute("select * from users where id = ?", (user_id,)).fetchone()


def new_session(user_id):
    token = secrets.token_urlsafe(32)
    with closing(connect()) as conn, conn:
        conn.execute("insert into sessions (token, user_id, created) values (?, ?, ?)", (token, user_id, time.time()))
    return {"token": token, "profile": profile(get_user(user_id))}


def create_account(username, password):
    username, password = str(username or "").strip(), str(password or "")
    if not USERNAME_RE.match(username):
        raise ApiError(400, "Usernames are 3-16 letters, numbers or _.")
    if len(password) < 6:
        raise ApiError(400, "Passwords need at least 6 characters.")
    salt = secrets.token_bytes(16)
    try:
        with closing(connect()) as conn, conn:
            cur = conn.execute("insert into users (username, pw_hash, salt, created) values (?, ?, ?, ?)",
                               (username, hash_password(password, salt), salt, time.time()))
            user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise ApiError(409, "That username is taken. Try another one.")
    return new_session(user_id)


def login(username, password):
    with closing(connect()) as conn:
        row = conn.execute("select * from users where username = ?", (str(username or "").strip(),)).fetchone()
    if not row or not hmac.compare_digest(row["pw_hash"], hash_password(str(password or ""), row["salt"])):
        raise ApiError(401, "Wrong username or password.")
    return new_session(row["id"])


def user_for_token(token):
    with closing(connect()) as conn:
        return conn.execute("select u.* from sessions s join users u on u.id = s.user_id where s.token = ?",
                            (token,)).fetchone()


def logout(token):
    with closing(connect()) as conn, conn:
        conn.execute("delete from sessions where token = ?", (token,))


def save_team(user_id, team):
    if team not in TEAMS:
        raise ApiError(400, "Unknown team.")
    with closing(connect()) as conn, conn:
        conn.execute("update users set team = ? where id = ?", (team, user_id))


def record_result(user_id, won):
    column = "wins" if won else "losses"
    with closing(connect()) as conn, conn:
        conn.execute(f"update users set {column} = {column} + 1 where id = ?", (user_id,))
    return profile(get_user(user_id))


# --------------------------------------------------------------------------- #
# Match rooms (in memory)
# --------------------------------------------------------------------------- #
class RoomHub:
    def __init__(self):
        self.cv = threading.Condition()
        self.rooms = {}

    def _event(self, room, sender, payload):
        room["next"] += 1
        room["events"].append({"id": room["next"], "from": sender, "payload": payload})
        del room["events"][:-300]
        self.cv.notify_all()

    def _snapshot(self, room):
        return {"t": "room", "code": room["code"], "overs": room["overs"], "wkts": room["wkts"],
                "players": [{"id": p["id"], "name": p["name"], "team": p["team"], "host": p["id"] == room["host"]}
                            for p in room["players"].values()]}

    def _joined(self, room):
        return {"code": room["code"], "room": self._snapshot(room), "since": room["next"]}

    def _room(self, code, user):
        room = self.rooms.get(str(code or "").upper())
        if not room or room["closed"]:
            raise ApiError(404, "No room found with that code.")
        if user["id"] not in room["players"]:
            raise ApiError(403, "You're not in this room.")
        return room

    def _add(self, room, user):
        room["players"][user["id"]] = {"id": user["id"], "name": user["username"], "team": user["team"], "seen": time.time()}
        self._event(room, 0, self._snapshot(room))

    def _remove(self, room, user_id):
        room["players"].pop(user_id, None)
        self._event(room, user_id, {"t": "leave"})
        self._event(room, 0, self._snapshot(room))
        if user_id == room["host"] or not room["players"]:
            room["closed"], room["closed_at"] = True, time.time()

    def create(self, user, overs, wkts):
        with self.cv:
            code = "".join(secrets.choice(CODE_CHARS) for _ in range(5))
            while code in self.rooms:
                code = "".join(secrets.choice(CODE_CHARS) for _ in range(5))
            room = {"code": code, "host": user["id"], "players": {}, "events": [], "next": 0, "closed": False,
                    "created": time.time(), "overs": max(1, min(50, int(overs or 2))), "wkts": max(1, min(10, int(wkts or 3)))}
            self.rooms[code] = room
            self._add(room, user)
            return self._joined(room)

    def join(self, user, code):
        with self.cv:
            room = self.rooms.get(str(code or "").upper().strip())
            if not room or room["closed"]:
                raise ApiError(404, "No room found with that code.")
            if user["id"] not in room["players"]:
                if len(room["players"]) >= 2:
                    raise ApiError(409, "That room is already full.")
                self._add(room, user)
            return self._joined(room)

    def leave(self, user, code):
        with self.cv:
            room = self.rooms.get(str(code or "").upper())
            if room and user["id"] in room["players"]:
                self._remove(room, user["id"])

    def set_team(self, user, code, team):
        with self.cv:
            room = self._room(code, user)
            room["players"][user["id"]]["team"] = team
            self._event(room, 0, self._snapshot(room))

    def send(self, user, code, payload):
        with self.cv:
            self._event(self._room(code, user), user["id"], payload)

    def poll(self, user, code, since):
        deadline = time.time() + POLL_WAIT
        with self.cv:
            while True:
                room = self.rooms.get(str(code or "").upper())
                if room is None:
                    raise ApiError(404, "This room has closed.")
                me = room["players"].get(user["id"])
                if me:
                    me["seen"] = time.time()
                events = [e for e in room["events"] if e["id"] > since and e["from"] != user["id"]]
                if events:
                    return {"events": events}
                if room["closed"] or me is None:
                    raise ApiError(404, "This room has closed.")
                remaining = deadline - time.time()
                if remaining <= 0:
                    return {"events": []}
                self.cv.wait(remaining)

    def reap(self):
        """Drop players who stopped polling, and forget old rooms."""
        now = time.time()
        with self.cv:
            for code, room in list(self.rooms.items()):
                for uid, p in list(room["players"].items()):
                    if now - p["seen"] > STALE_AFTER:
                        self._remove(room, uid)
                if (room["closed"] and now - room.get("closed_at", now) > 30) or now - room["created"] > 12 * 3600:
                    del self.rooms[code]


HUB = RoomHub()


# --------------------------------------------------------------------------- #
# HTTP API
# --------------------------------------------------------------------------- #
def _auth(h, body):
    header = h.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else body.get("token")
    row = user_for_token(token) if token else None
    if not row:
        raise ApiError(401, "Please sign in again.")
    return dict(row)


ROUTES = {
    ("POST", "/api/signup"): lambda h, b, q: create_account(b.get("username"), b.get("password")),
    ("POST", "/api/login"): lambda h, b, q: login(b.get("username"), b.get("password")),
    ("GET", "/api/me"): lambda h, b, q: {"profile": profile(_auth(h, b))},
    ("POST", "/api/logout"): lambda h, b, q: (logout(h.headers.get("Authorization", "")[7:]), {"ok": True})[1],
    ("POST", "/api/team"): lambda h, b, q: (save_team(_auth(h, b)["id"], b.get("team")), {"ok": True})[1],
    ("POST", "/api/result"): lambda h, b, q: {"profile": record_result(_auth(h, b)["id"], bool(b.get("won")))},
    ("POST", "/api/room/create"): lambda h, b, q: HUB.create(_auth(h, b), b.get("overs"), b.get("wkts")),
    ("POST", "/api/room/join"): lambda h, b, q: HUB.join(_auth(h, b), b.get("code")),
    ("POST", "/api/room/leave"): lambda h, b, q: (HUB.leave(_auth(h, b), b.get("code")), {"ok": True})[1],
    ("POST", "/api/room/team"): lambda h, b, q: _room_team(_auth(h, b), b),
    ("POST", "/api/send"): lambda h, b, q: (HUB.send(_auth(h, b), b.get("code"), b.get("payload")), {"ok": True})[1],
    ("GET", "/api/poll"): lambda h, b, q: HUB.poll(_auth(h, b), q.get("code", [""])[0], int(q.get("since", ["0"])[0] or 0)),
}


def _room_team(user, body):
    team = body.get("team")
    save_team(user["id"], team)
    HUB.set_team(user, body.get("code"), team)
    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    server_version = "CricketLeague3D/1.0"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _reply(self, status, payload=None, body=None, content_type="application/json; charset=utf-8"):
        data = body if body is not None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._reply(204, body=b"")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "Request too large.")
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError(400, "Bad request.")
        return data if isinstance(data, dict) else {}

    def _handle(self, method):
        url = urlparse(self.path)
        try:
            if method == "GET" and url.path in ("/", "/index.html"):
                page = GAME_FILE.read_text(encoding="utf-8").replace("__GAME_SERVER__", "")
                return self._reply(200, body=page.encode(), content_type="text/html; charset=utf-8")
            if method == "GET" and url.path == "/api/health":
                return self._reply(200, {"ok": True})
            route = ROUTES.get((method, url.path))
            if not route:
                raise ApiError(404, "Not found.")
            body = self._body() if method == "POST" else {}
            self._reply(200, route(self, body, parse_qs(url.query)))
        except ApiError as e:
            self._reply(e.status, {"error": e.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._reply(500, {"error": "Something went wrong on the game server."})


# --------------------------------------------------------------------------- #
# Starting the server
# --------------------------------------------------------------------------- #
def lan_ip():
    """This computer's address on the local network (what friends type in)."""
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _reaper():
    while True:
        time.sleep(5)
        HUB.reap()


_server = None


def start_in_background(port=DEFAULT_PORT):
    """Start the server on a background thread. Returns False if the port is already taken
    (usually because the server is already running)."""
    global _server
    if _server:
        return True
    init_db()
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    except OSError:
        return False
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=_reaper, daemon=True).start()
    _server = srv
    return True


def main():
    parser = argparse.ArgumentParser(description="Cricket League 3D online game server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    init_db()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=_reaper, daemon=True).start()
    print("🏏 Cricket League 3D server is running")
    print(f"   On this computer:        http://localhost:{args.port}")
    print(f"   For friends on your Wi-Fi: http://{lan_ip()}:{args.port}")
    print("   Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
