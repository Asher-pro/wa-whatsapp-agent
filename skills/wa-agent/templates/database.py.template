"""
Conversation memory using SQLite.
Stores message history per phone number for multi-turn conversations.
"""

import sqlite3
import os
from config import settings


def _get_db_path() -> str:
    """Get database file path, creating directory if needed."""
    db_path = settings.DATABASE_PATH
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    return db_path


def _connect():
    """Create a database connection."""
    return sqlite3.connect(_get_db_path())


def init_db():
    """Create the messages table if it doesn't exist."""
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_phone
        ON messages(phone, timestamp DESC)
    """)
    conn.commit()
    conn.close()


def save_message(phone: str, role: str, content: str):
    """Save a message to the database."""
    conn = _connect()
    conn.execute(
        "INSERT INTO messages (phone, role, content) VALUES (?, ?, ?)",
        (phone, role, content),
    )
    conn.commit()
    conn.close()


def get_history(phone: str, limit: int = 20) -> list[dict]:
    """Get recent conversation history for a phone number."""
    conn = _connect()
    cursor = conn.execute(
        """
        SELECT role, content FROM (
            SELECT role, content, timestamp
            FROM messages
            WHERE phone = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ) sub ORDER BY timestamp ASC
        """,
        (phone, limit),
    )
    history = [{"role": row[0], "content": row[1]} for row in cursor.fetchall()]
    conn.close()
    return history
