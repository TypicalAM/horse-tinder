"""SQLite storage: schema, seeding and queries."""

import json
import sqlite3
from pathlib import Path

SEED_FILE = Path(__file__).with_name("horses.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    token       TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS horses (
    id             INTEGER PRIMARY KEY,
    slug           TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    age            INTEGER NOT NULL,
    breed          TEXT NOT NULL,
    location       TEXT NOT NULL,
    bio            TEXT NOT NULL,
    interests      TEXT NOT NULL,
    pickiness      REAL NOT NULL,
    photo          TEXT NOT NULL,
    photo_position TEXT NOT NULL DEFAULT 'center',
    photo_artist   TEXT NOT NULL,
    photo_license  TEXT NOT NULL,
    photo_source   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS swipes (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    horse_id    INTEGER NOT NULL REFERENCES horses(id) ON DELETE CASCADE,
    liked       INTEGER NOT NULL,
    matched     INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, horse_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    horse_id    INTEGER NOT NULL REFERENCES horses(id) ON DELETE CASCADE,
    from_horse  INTEGER NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS messages_thread ON messages (user_id, horse_id, id);
"""

HORSE_COLUMNS = (
    "slug, name, age, breed, location, bio, interests, pickiness, "
    "photo, photo_position, photo_artist, photo_license, photo_source"
)


def connect(path: str) -> sqlite3.Connection:
    # FastAPI may run a request's dependencies and handler on different worker
    # threads. Each connection still serves one request at a time.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        seed(conn)
    conn.close()


def seed(conn: sqlite3.Connection) -> None:
    horses = json.loads(SEED_FILE.read_text())
    conn.executemany(
        f"""
        INSERT INTO horses ({HORSE_COLUMNS})
        VALUES (:slug, :name, :age, :breed, :location, :bio, :interests, :pickiness,
                :photo, :photo_position, :photo_artist, :photo_license, :photo_source)
        ON CONFLICT (slug) DO UPDATE SET
            name = excluded.name, age = excluded.age, breed = excluded.breed,
            location = excluded.location, bio = excluded.bio,
            interests = excluded.interests, pickiness = excluded.pickiness,
            photo = excluded.photo, photo_position = excluded.photo_position,
            photo_artist = excluded.photo_artist,
            photo_license = excluded.photo_license, photo_source = excluded.photo_source
        """,
        [
            {
                **h,
                "interests": json.dumps(h["interests"]),
                "photo_position": h.get("photo_position", "center"),
            }
            for h in horses
        ],
    )


def horse_dict(row: sqlite3.Row) -> dict:
    horse = dict(row)
    horse["interests"] = json.loads(horse["interests"])
    horse.pop("pickiness", None)
    return horse


def user_for_token(conn: sqlite3.Connection, token: str) -> int | None:
    row = conn.execute("SELECT id FROM users WHERE token = ?", (token,)).fetchone()
    return row["id"] if row else None


def create_user(conn: sqlite3.Connection, token: str) -> int:
    return conn.execute("INSERT INTO users (token) VALUES (?)", (token,)).lastrowid


def get_horse(conn: sqlite3.Connection, horse_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM horses WHERE id = ?", (horse_id,)).fetchone()


def next_horses(conn: sqlite3.Connection, user_id: int, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT h.* FROM horses h
        WHERE NOT EXISTS (
            SELECT 1 FROM swipes s WHERE s.user_id = ? AND s.horse_id = h.id
        )
        ORDER BY h.id
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [horse_dict(r) for r in rows]


def record_swipe(
    conn: sqlite3.Connection, user_id: int, horse_id: int, liked: bool, matched: bool
) -> bool:
    """Store a swipe. Returns False if the user already swiped this horse."""
    cur = conn.execute(
        """
        INSERT INTO swipes (user_id, horse_id, liked, matched) VALUES (?, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (user_id, horse_id, int(liked), int(matched)),
    )
    return cur.rowcount == 1


def matches(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT h.*, s.created_at AS matched_at,
               (SELECT body FROM messages m
                WHERE m.user_id = s.user_id AND m.horse_id = h.id
                ORDER BY m.id DESC LIMIT 1) AS last_message
        FROM swipes s JOIN horses h ON h.id = s.horse_id
        WHERE s.user_id = ? AND s.matched = 1
        ORDER BY s.created_at DESC, h.id DESC
        """,
        (user_id,),
    ).fetchall()
    return [horse_dict(r) for r in rows]


def is_match(conn: sqlite3.Connection, user_id: int, horse_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM swipes WHERE user_id = ? AND horse_id = ? AND matched = 1",
        (user_id, horse_id),
    ).fetchone()
    return row is not None


def messages(conn: sqlite3.Connection, user_id: int, horse_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, from_horse, body, created_at FROM messages
        WHERE user_id = ? AND horse_id = ? ORDER BY id
        """,
        (user_id, horse_id),
    ).fetchall()
    return [{**dict(r), "from_horse": bool(r["from_horse"])} for r in rows]


def add_message(
    conn: sqlite3.Connection, user_id: int, horse_id: int, from_horse: bool, body: str
) -> None:
    conn.execute(
        "INSERT INTO messages (user_id, horse_id, from_horse, body) VALUES (?, ?, ?, ?)",
        (user_id, horse_id, int(from_horse), body),
    )


def reset(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM swipes WHERE user_id = ?", (user_id,))


def stats(conn: sqlite3.Connection, user_id: int) -> dict:
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM horses) AS horses,
            COUNT(s.horse_id) AS swiped,
            COALESCE(SUM(s.liked), 0) AS liked,
            COALESCE(SUM(s.matched), 0) AS matched
        FROM swipes s WHERE s.user_id = ?
        """,
        (user_id,),
    ).fetchone()
    return dict(row)
