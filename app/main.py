import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.database import connect, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Wishlist API", lifespan=lifespan)


class Claim(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/gifts")
def get_gifts():
    db = connect()
    try:
        rows = db.execute("""
            SELECT g.id, g.title, g.description, g.image,
                   r.gift_id IS NOT NULL AS reserved
            FROM gifts AS g
            LEFT JOIN reservations AS r ON r.gift_id = g.id
            ORDER BY g.id DESC
        """)
        return [dict(row) | {"reserved": bool(row["reserved"])} for row in rows]
    finally:
        db.close()


@app.post("/gifts/{gift_id}/claim", status_code=201)
def claim_gift(gift_id: int, claim: Claim):
    name = claim.name.strip()
    if not name:
        raise HTTPException(422, "Name cannot be empty")

    db = connect()
    try:
        try:
            db.execute(
                "INSERT INTO reservations (gift_id, name) VALUES (?, ?)",
                (gift_id, name),
            )
            db.commit()
        except sqlite3.IntegrityError:
            if db.execute(
                "SELECT 1 FROM gifts WHERE id = ?", (gift_id,)
            ).fetchone() is None:
                raise HTTPException(404, "Gift not found")
            raise HTTPException(409, "Gift already reserved")
    finally:
        db.close()

    return {"message": "Gift reserved"}
