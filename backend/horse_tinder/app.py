"""HTTP API for Horse Tinder. Also serves the static frontend."""

import os
import random
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db

SESSION_COOKIE = "ht_session"
DEFAULT_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

HORSE_REPLIES = [
    "Neigh 😏",
    "Do you have any carrots? Asking for a friend. The friend is me.",
    "I'm more of a hay person than a text person, but go on.",
    "*flicks tail flirtatiously*",
    "My herd says hi. They're watching. They're always watching.",
    "Sorry, was grazing. What did I miss?",
    "Is that a sugar cube in your pocket or are you just happy to see me?",
    "Hoof-ually I think we'd get along great.",
    "Let's meet at the paddock. Bring snacks.",
    "Whinny whinny 🐴",
]


class SwipeIn(BaseModel):
    horse_id: int
    liked: bool


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=500)


def create_app(
    db_path: str | None = None,
    frontend_dir: str | Path | None = None,
    rng: random.Random | None = None,
) -> FastAPI:
    db_path = db_path or os.environ.get("HORSE_TINDER_DB", "data/horse-tinder.db")
    frontend_dir = Path(frontend_dir or os.environ.get("HORSE_TINDER_FRONTEND", DEFAULT_FRONTEND))
    rng = rng or random.Random()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.init(db_path)
        yield

    app = FastAPI(title="Horse Tinder", lifespan=lifespan)

    def get_conn() -> Iterator[sqlite3.Connection]:
        conn = db.connect(db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def current_user(request: Request, response: Response, conn: Conn) -> int:
        token = request.cookies.get(SESSION_COOKIE)
        user_id = db.user_for_token(conn, token) if token else None
        if user_id is None:
            token = secrets.token_urlsafe(32)
            user_id = db.create_user(conn, token)
            response.set_cookie(
                SESSION_COOKIE,
                token,
                httponly=True,
                samesite="lax",
                max_age=60 * 60 * 24 * 365,
            )
        return user_id

    User = Annotated[int, Depends(current_user)]

    def matched_horse(conn: sqlite3.Connection, user_id: int, horse_id: int) -> None:
        if not db.is_match(conn, user_id, horse_id):
            raise HTTPException(404, "No match with this horse")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/horses")
    def next_horses(conn: Conn, user: User, limit: int = 5) -> dict:
        limit = max(1, min(limit, 20))
        return {"horses": db.next_horses(conn, user, limit)}

    @app.post("/api/swipes")
    def swipe(payload: SwipeIn, conn: Conn, user: User) -> dict:
        horse = db.get_horse(conn, payload.horse_id)
        if horse is None:
            raise HTTPException(404, "Horse not found")
        matched = payload.liked and rng.random() >= horse["pickiness"]
        if not db.record_swipe(conn, user, horse["id"], payload.liked, matched):
            raise HTTPException(409, "Already swiped on this horse")
        if matched:
            db.add_message(conn, user, horse["id"], True, rng.choice(HORSE_REPLIES))
        return {"matched": matched, "horse": db.horse_dict(horse) if matched else None}

    @app.get("/api/matches")
    def list_matches(conn: Conn, user: User) -> dict:
        return {"matches": db.matches(conn, user)}

    @app.get("/api/matches/{horse_id}/messages")
    def list_messages(horse_id: int, conn: Conn, user: User) -> dict:
        matched_horse(conn, user, horse_id)
        return {"messages": db.messages(conn, user, horse_id)}

    @app.post("/api/matches/{horse_id}/messages")
    def send_message(horse_id: int, payload: MessageIn, conn: Conn, user: User) -> dict:
        matched_horse(conn, user, horse_id)
        db.add_message(conn, user, horse_id, False, payload.body.strip())
        db.add_message(conn, user, horse_id, True, rng.choice(HORSE_REPLIES))
        return {"messages": db.messages(conn, user, horse_id)}

    @app.get("/api/stats")
    def stats(conn: Conn, user: User) -> dict:
        return db.stats(conn, user)

    @app.post("/api/reset")
    def reset(conn: Conn, user: User) -> dict:
        db.reset(conn, user)
        return {"status": "ok"}

    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app


def main() -> None:
    import uvicorn

    uvicorn.run(
        create_app(),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
