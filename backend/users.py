import os
import sqlite3
from pathlib import Path

from backend.auth import hash_password, verify_password

DB_PATH = Path(__file__).resolve().parent.parent / "janus_auth.db"


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def initialize_users():
    """Create the user table if it does not exist."""
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            )
        """)


def get_user(username: str):
    """Find a user by username."""
    with connect() as db:
        row = db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    return dict(row) if row else None


def create_user(username: str, password: str, is_admin=False):
    """Create a user with a hashed password."""
    if not username.strip() or len(password) < 8:
        raise ValueError("Username required and password must be 8+ characters")

    hashed = hash_password(password)

    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO users (username, password_hash, is_admin)
            VALUES (?, ?, ?)
            """,
            (username, hashed, int(is_admin)),
        )

        user_id = cursor.lastrowid

    return {
        "id": user_id,
        "username": username,
        "is_admin": bool(is_admin),
    }


def authenticate_user(username: str, password: str):
    """Check credentials against the database."""
    user = get_user(username)

    if not user:
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    return user

def bootstrap_admin():
    """Create the first administrator from environment variables."""
    initialize_users()

    with connect() as db:
        existing_admin = db.execute(
            "SELECT id FROM users WHERE is_admin = 1 LIMIT 1"
        ).fetchone()

    if existing_admin:
        return

    username = os.getenv("JANUS_ADMIN_USER")
    password = os.getenv("JANUS_ADMIN_PASSWORD")

    if not username or not password:
        raise RuntimeError(
            "No admin exists. Set JANUS_ADMIN_USER and "
            "JANUS_ADMIN_PASSWORD before starting Janus."
        )

    create_user(username, password, is_admin=True)
