import sqlite3
from backend.users import connect


def initialize_alert_rules():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS alert_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                metric TEXT NOT NULL,
                operator TEXT NOT NULL,
                threshold REAL NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL
            )
        """)


def create_alert_rule(device_id, metric, operator, threshold, created_by):
    with connect() as db:
        cursor = db.execute("""
            INSERT INTO alert_rules
            (device_id, metric, operator, threshold, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (device_id, metric, operator, threshold, created_by))

        return cursor.lastrowid


def list_alert_rules(device_id):
    with connect() as db:
        rows = db.execute("""
            SELECT * FROM alert_rules
            WHERE device_id = ?
            ORDER BY id
        """, (device_id,)).fetchall()

        return [dict(row) for row in rows]


def get_alert_rule(rule_id):
    with connect() as db:
        row = db.execute(
            "SELECT * FROM alert_rules WHERE id = ?",
            (rule_id,)
        ).fetchone()

        return dict(row) if row else None


def update_alert_rule(rule_id, metric, operator, threshold, enabled):
    with connect() as db:
        cursor = db.execute("""
            UPDATE alert_rules
            SET metric = ?, operator = ?, threshold = ?, enabled = ?
            WHERE id = ?
        """, (metric, operator, threshold, int(enabled), rule_id))

        return cursor.rowcount > 0


def delete_alert_rule(rule_id):
    with connect() as db:
        cursor = db.execute(
            "DELETE FROM alert_rules WHERE id = ?",
            (rule_id,)
        )

        return cursor.rowcount > 0


initialize_alert_rules()
