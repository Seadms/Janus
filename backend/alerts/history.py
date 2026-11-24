from backend.users import connect


def initialize_alert_history():
    """Create a table to store triggered alerts."""
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                rule_id INTEGER NOT NULL,
                metric TEXT NOT NULL,
                value REAL NOT NULL,
                operator TEXT NOT NULL,
                threshold REAL NOT NULL,
                message TEXT NOT NULL,
                triggered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


def save_alert(alert: dict):
    """Save a triggered alert to the shared database."""
    with connect() as db:
        cursor = db.execute("""
            INSERT INTO alert_history (
                device_id, rule_id, metric, value,
                operator, threshold, message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            alert["device_id"],
            alert["rule_id"],
            alert["metric"],
            alert["value"],
            alert["operator"],
            alert["threshold"],
            alert["message"],
        ))

        return cursor.lastrowid


initialize_alert_history()

def list_user_alerts(username: str):
    """Return alerts for devices the user is authorized to view."""
    from backend.users import get_user

    user = get_user(username)
    if user is None:
        return []

    with connect() as db:
        if user["is_admin"]:
            rows = db.execute("""
                SELECT * FROM alert_history
                ORDER BY triggered_at DESC, id DESC
            """).fetchall()
        else:
            rows = db.execute("""
                SELECT ah.*
                FROM alert_history AS ah
                INNER JOIN device_permissions AS dp
                    ON ah.device_id = dp.device_id
                WHERE dp.username = ?
                ORDER BY ah.triggered_at DESC, ah.id DESC
            """, (username,)).fetchall()

    return [dict(row) for row in rows]