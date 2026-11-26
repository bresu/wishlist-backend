import os
import sqlite3

DATABASE_PATH = os.getenv("DATABASE_PATH", "wishlist.db")


def connect():
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    db = connect()
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL CHECK (length(trim(title)) > 0),
                description TEXT NOT NULL DEFAULT '',
                image TEXT
            );

            CREATE TABLE IF NOT EXISTS reservations (
                gift_id INTEGER PRIMARY KEY REFERENCES gifts(id) ON DELETE CASCADE,
                name TEXT NOT NULL CHECK (length(trim(name)) > 0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        db.commit()
    finally:
        db.close()
