
import sqlite3

from fastapi import HTTPException

from backend.users import connect, get_user

ROLE_LEVELS = {
    "viewer": 1,
    "operator": 2,
    "admin": 3,
}


def initialize_permissions():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS device_permissions (
                device_id TEXT NOT NULL,
                username TEXT NOT NULL,
                role TEXT NOT NULL
                    CHECK (role IN ('viewer', 'operator', 'admin')),
                PRIMARY KEY (device_id, username)
            )
        """)


def get_device_role(username: str, device_id: str):
    with connect() as db:
        row = db.execute(
            """
            SELECT role FROM device_permissions
            WHERE username = ? AND device_id = ?
            """,
            (username, device_id),
        ).fetchone()

    return row["role"] if row else None


def require_device_role(username: str, device_id: str, minimum_role: str):
    user = get_user(username)

    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    # Global administrators can manage all devices.
    if user["is_admin"]:
        return "admin"

    role = get_device_role(username, device_id)

    if role is None or ROLE_LEVELS[role] < ROLE_LEVELS[minimum_role]:
        raise HTTPException(
            status_code=403,
            detail=f"{minimum_role} permission required for device {device_id}",
        )

    return role


def set_device_role(device_id: str, username: str, role: str):
    if role not in ROLE_LEVELS:
        raise ValueError("Invalid device role")

    if get_user(username) is None:
        raise HTTPException(status_code=404, detail="User not found")

    with connect() as db:
        db.execute(
            """
            INSERT INTO device_permissions (device_id, username, role)
            VALUES (?, ?, ?)
            ON CONFLICT(device_id, username)
            DO UPDATE SET role = excluded.role
            """,
            (device_id, username, role),
        )

    return {"device_id": device_id, "username": username, "role": role}
