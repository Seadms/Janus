"""Opt-in local Janus workspace for frontend development and simulator demos."""
import asyncio
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parents[1]
OPEN_LOCAL_PREVIEW = os.environ.get("JANUS_OPEN_LOCAL_PREVIEW") == "1"
RETENTION = 14 * 86400
SESSION_AGE = 8 * 3600
OPERATORS = {
    ">": lambda value, threshold: value > threshold,
    "<": lambda value, threshold: value < threshold,
    ">=": lambda value, threshold: value >= threshold,
    "<=": lambda value, threshold: value <= threshold,
}
schema_sql = """
CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, schema TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS access (
    device TEXT REFERENCES devices(id) ON DELETE CASCADE,
    username TEXT REFERENCES users(username) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('viewer', 'operator')),
    PRIMARY KEY(device, username)
);
CREATE TABLE IF NOT EXISTS readings (
    device TEXT REFERENCES devices(id) ON DELETE CASCADE, timestamp REAL, data TEXT
);
CREATE INDEX IF NOT EXISTS readings_device_time ON readings(device, timestamp);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY, device TEXT REFERENCES devices(id) ON DELETE CASCADE,
    field TEXT NOT NULL, op TEXT NOT NULL, threshold REAL NOT NULL, enabled INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY, device TEXT REFERENCES devices(id) ON DELETE CASCADE,
    timestamp REAL NOT NULL, field TEXT NOT NULL, op TEXT NOT NULL, threshold REAL NOT NULL, value REAL NOT NULL
);
"""
sessions = {}
bridges = {}
online = set()
last_reading = {}
crossed = set()
dashboards = {}


def password_digest(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 300_000)
    return salt + "$" + digest.hex()


def store_schema(schema):
    db.execute("INSERT INTO devices VALUES (?, ?)", (schema["device_id"], json.dumps(schema)))


@asynccontextmanager
async def lifespan(_app):
    global db
    db = sqlite3.connect(os.environ.get("JANUS_DB", ROOT / ".janus-workspace.sqlite3"), isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(schema_sql)
    try:
        if not db.execute("SELECT 1 FROM users WHERE admin = 1").fetchone():
            password = os.environ.get("JANUS_ADMIN_PASSWORD", "")
            if not password and OPEN_LOCAL_PREVIEW:
                password = secrets.token_urlsafe(24)
            if len(password) < 8:
                raise RuntimeError("Set JANUS_ADMIN_PASSWORD (8+ characters) to initialize the local workspace.")
            username = os.environ.get("JANUS_ADMIN_USER", "admin")
            db.execute("BEGIN")
            try:
                db.execute("INSERT INTO users VALUES (?, ?, 1)", (username, password_digest(password)))
                schema = json.loads((ROOT / "schemas" / "nucleo_tilt_motor.json").read_text())
                store_schema(schema)
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        cleanup = asyncio.create_task(prune())
        try:
            yield
        finally:
            cleanup.cancel()
            try:
                await cleanup
            except asyncio.CancelledError:
                pass
    finally:
        db.close()


async def prune():
    while True:
        now = time.time()
        cutoff = now - RETENTION
        db.execute("DELETE FROM readings WHERE timestamp < ?", (cutoff,))
        db.execute("DELETE FROM alerts WHERE timestamp < ?", (cutoff,))
        for token, session in list(sessions.items()):
            if session[2] <= now:
                sessions.pop(token, None)
        await asyncio.sleep(3600)


app = FastAPI(title="Janus Workspace", lifespan=lifespan)
if OPEN_LOCAL_PREVIEW:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
app.mount("/frontend", StaticFiles(directory=ROOT / "frontend"), name="frontend")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(ROOT / "frontend" / "index.html")


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=256)


class Command(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)


class Grant(BaseModel):
    username: str
    role: str


class Rule(BaseModel):
    field: str
    op: str
    threshold: float
    enabled: bool = True


def actor(token):
    session = sessions.get(token)
    if not session:
        return None
    username, admin, expiry = session
    if time.time() >= expiry:
        sessions.pop(token, None)
        return None
    return {"username": username, "admin": admin}


def authenticated(request):
    user = actor(request.cookies.get("janus_session"))
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    return user


def administrator(request):
    user = authenticated(request)
    if not user["admin"]:
        raise HTTPException(403, "Administrator access is required.")
    return user


def role(user, device):
    if user["admin"]:
        return "administrator"
    grant = db.execute(
        "SELECT role FROM access WHERE device = ? AND username = ?", (device, user["username"])
    ).fetchone()
    return grant["role"] if grant else None


def device_schema(device):
    row = db.execute("SELECT schema FROM devices WHERE id = ?", (device,)).fetchone()
    if row is None:
        raise HTTPException(404, "Device not found.")
    return json.loads(row["schema"])


def device_access(request, device, *, command=False):
    access = role(authenticated(request), device)
    if access is None or (command and access == "viewer"):
        raise HTTPException(403, "You do not have access to this action.")
    return device_schema(device)


def start_session(request, response, username, admin):
    sessions.pop(request.cookies.get("janus_session"), None)
    token = secrets.token_urlsafe(32)
    sessions[token] = (username, bool(admin), time.time() + SESSION_AGE)
    response.set_cookie("janus_session", token, httponly=True, samesite="strict", max_age=SESSION_AGE)
    return actor(token)


@app.get("/api/session")
async def session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    user = actor(request.cookies.get("janus_session"))
    if OPEN_LOCAL_PREVIEW:
        if request.client.host not in ("127.0.0.1", "::1"):
            raise HTTPException(403, "Open this preview on the computer running Janus.")
        if request.headers.get("sec-fetch-site") not in (None, "none", "same-origin"):
            raise HTTPException(403, "Open Janus directly to start the preview.")
        if not user or not user["admin"]:
            admin = db.execute("SELECT username FROM users WHERE admin = 1 LIMIT 1").fetchone()
            user = start_session(request, response, admin["username"], True)
    return {"user": user, "open_preview": OPEN_LOCAL_PREVIEW}


@app.post("/api/session")
async def login(data: Credentials, request: Request, response: Response):
    row = db.execute("SELECT * FROM users WHERE username = ?", (data.username,)).fetchone()
    candidate = password_digest(data.password, row["password"].split("$")[0] if row else "00" * 16)
    if not row or not hmac.compare_digest(candidate, row["password"]):
        raise HTTPException(401, "Incorrect username or password.")
    return {"user": start_session(request, response, data.username, row["admin"])}


@app.delete("/api/session")
async def logout(request: Request, response: Response):
    sessions.pop(request.cookies.get("janus_session"), None)
    response.delete_cookie("janus_session")
    return {"ok": True}


@app.get("/api/devices")
async def devices(request: Request):
    user = authenticated(request)
    details = {}
    for row in db.execute("SELECT * FROM devices ORDER BY id"):
        device = row["id"]
        access = role(user, device)
        if access:
            details[device] = {
                "connected": device in online, "role": access, "name": json.loads(row["schema"])["name"],
                "last_seen": last_reading.get(device),
            }
    return {"devices": list(details), "device_details": details}


@app.get("/api/devices/{device}/schema")
async def get_schema(device: str, request: Request):
    return device_access(request, device)


def valid_value(value, field):
    kind = field["type"]
    if kind in ("number", "integer"):
        is_number = type(value) is int or (type(value) is float and math.isfinite(value))
        return (
            is_number and (kind != "integer" or type(value) is int)
            and field.get("min", -math.inf) <= value <= field.get("max", math.inf)
        )
    return (kind == "boolean" and isinstance(value, bool)) or (kind == "string" and isinstance(value, str))


def validate_fields(fields):
    if not isinstance(fields, dict):
        raise ValueError("Telemetry and command arguments must be objects.")
    for key, field in fields.items():
        if not key or not isinstance(field, dict) or field.get("type") not in ("number", "integer", "boolean", "string"):
            raise ValueError("Each field must have a supported type.")
        for key in ("label", "unit"):
            if key in field and not isinstance(field[key], str):
                raise ValueError("Field labels and units must be text.")
        for key in ("min", "max"):
            if key in field and not (type(field[key]) in (int, float) and math.isfinite(field[key])):
                raise ValueError("Field bounds must be finite numbers.")
        if field.get("min", -math.inf) > field.get("max", math.inf):
            raise ValueError("Minimum must be at most maximum.")


@app.post("/api/devices", status_code=201)
async def register(request: Request, schema: dict):
    administrator(request)
    try:
        if not isinstance(schema.get("device_id"), str) or not re.fullmatch(r"[\w-]{1,80}", schema["device_id"]):
            raise ValueError("Device ID must contain letters, numbers, underscores, or hyphens.")
        if not isinstance(schema.get("name"), str) or not schema["name"].strip():
            raise ValueError("A device name is required.")
        if "description" in schema and not isinstance(schema["description"], str):
            raise ValueError("The description must be text.")
        if "rate_hz" in schema and not (type(schema["rate_hz"]) in (int, float) and 0 < schema["rate_hz"] <= 1000):
            raise ValueError("Sample rate must be between 0 and 1000 Hz.")
        validate_fields(schema.get("telemetry"))
        commands = schema.get("commands", {})
        if not isinstance(commands, dict):
            raise ValueError("Commands must be an object.")
        for command in commands.values():
            if not isinstance(command, dict) or not isinstance(command.get("label", ""), str):
                raise ValueError("Invalid command definition.")
            validate_fields(command.get("args", {}))
        store_schema(schema)
    except (ValueError, OverflowError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "A device with that ID already exists.") from exc
    return {"id": schema["device_id"]}


@app.delete("/api/devices/{device}")
async def remove(request: Request, device: str):
    administrator(request)
    device_schema(device)
    members = db.execute("SELECT username FROM access WHERE device = ?", (device,)).fetchall()
    db.execute("DELETE FROM devices WHERE id = ?", (device,))
    online.discard(device)
    last_reading.pop(device, None)
    crossed.difference_update({entry for entry in crossed if entry[0] == device})
    await broadcast(device, {"type": "device_removed"})
    for member in members:
        await notify_access(member["username"])
    return {"ok": True}


@app.get("/api/users")
async def users(request: Request):
    administrator(request)
    return {"users": [dict(row) for row in db.execute("SELECT username, admin FROM users ORDER BY username")]}


@app.post("/api/users", status_code=201)
async def create_user(request: Request, data: Credentials):
    administrator(request)
    if len(data.password) < 8:
        raise HTTPException(422, "Use at least 8 characters for the starting password.")
    try:
        db.execute("INSERT INTO users VALUES (?, ?, 0)", (data.username, password_digest(data.password)))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "That username already exists.") from exc
    return {"username": data.username}


@app.get("/api/devices/{device}/access")
async def access(request: Request, device: str):
    administrator(request)
    device_schema(device)
    return {"access": [dict(row) for row in db.execute(
        "SELECT username, role FROM access WHERE device = ? ORDER BY username", (device,)
    )]}


@app.put("/api/devices/{device}/access")
async def grant(request: Request, device: str, data: Grant):
    administrator(request)
    device_schema(device)
    user = db.execute("SELECT admin FROM users WHERE username = ?", (data.username,)).fetchone()
    if not user or user["admin"] or data.role not in ("viewer", "operator"):
        raise HTTPException(422, "Choose a standard user and a viewer or operator role.")
    db.execute("INSERT OR REPLACE INTO access VALUES (?, ?, ?)", (device, data.username, data.role))
    await notify_access(data.username)
    return {"ok": True}


@app.delete("/api/devices/{device}/access/{username}")
async def revoke(request: Request, device: str, username: str):
    administrator(request)
    device_schema(device)
    db.execute("DELETE FROM access WHERE device = ? AND username = ?", (device, username))
    await notify_access(username)
    return {"ok": True}


@app.get("/api/devices/{device}/rules")
async def rules(request: Request, device: str):
    administrator(request)
    device_schema(device)
    return {"rules": [dict(row) for row in db.execute("SELECT * FROM rules WHERE device = ? ORDER BY id", (device,))]}


def check_rule(device, data):
    field = device_schema(device)["telemetry"].get(data.field, {})
    if field.get("type") not in ("number", "integer") or data.op not in OPERATORS or not math.isfinite(data.threshold):
        raise HTTPException(422, "Choose a numeric field, comparison, and finite threshold.")
    return (data.field, data.op, data.threshold, data.enabled)


@app.post("/api/devices/{device}/rules", status_code=201)
async def create_rule(request: Request, device: str, data: Rule):
    administrator(request)
    values = check_rule(device, data)
    row = db.execute("INSERT INTO rules(device, field, op, threshold, enabled) VALUES (?, ?, ?, ?, ?)", (device, *values))
    return {"id": row.lastrowid}


@app.put("/api/devices/{device}/rules/{rule_id}")
async def update_rule(request: Request, device: str, rule_id: int, data: Rule):
    administrator(request)
    values = check_rule(device, data)
    row = db.execute(
        "UPDATE rules SET field = ?, op = ?, threshold = ?, enabled = ? WHERE device = ? AND id = ?",
        (*values, device, rule_id),
    )
    if not row.rowcount:
        raise HTTPException(404, "Rule not found.")
    crossed.discard((device, rule_id))
    return {"ok": True}


@app.delete("/api/devices/{device}/rules/{rule_id}")
async def delete_rule(request: Request, device: str, rule_id: int):
    administrator(request)
    db.execute("DELETE FROM rules WHERE device = ? AND id = ?", (device, rule_id))
    crossed.discard((device, rule_id))
    return {"ok": True}


@app.get("/api/devices/{device}/telemetry")
async def history(request: Request, device: str, start: float, end: float, fields: list[str] = Query()):
    schema = device_access(request, device)
    selected = list(dict.fromkeys(fields))
    if not selected or any(key not in schema["telemetry"] for key in selected):
        raise HTTPException(422, "Choose fields from this device's schema.")
    if not (math.isfinite(start) and math.isfinite(end) and start < end and end - start <= RETENTION):
        raise HTTPException(422, "Select a time range of up to 14 days.")
    step = max((end - start) / 600, 0.1)
    rows = db.execute(
        """SELECT MIN(timestamp) AS timestamp, data FROM readings
        WHERE device = ? AND timestamp BETWEEN ? AND ?
        GROUP BY CAST((timestamp - ?) / ? AS INTEGER) ORDER BY timestamp""",
        (device, start, end, start, step),
    )
    return {"samples": [
        {"timestamp": row["timestamp"], "data": {key: json.loads(row["data"]).get(key) for key in selected}}
        for row in rows
    ]}


@app.get("/api/alerts")
async def alerts(request: Request, device: str):
    device_access(request, device)
    rows = db.execute("SELECT * FROM alerts WHERE device = ? ORDER BY id DESC LIMIT 100", (device,))
    return {"alerts": [dict(row) for row in rows]}


@app.post("/api/devices/{device}/commands")
async def send_command(device: str, command: Command, request: Request):
    schema = device_access(request, device, command=True)
    definition = schema.get("commands", {}).get(command.name)
    if definition is None:
        raise HTTPException(422, "Command is not in this device's schema.")
    fields = definition.get("args", {})
    if command.args.keys() != fields.keys() or any(not valid_value(command.args[key], field) for key, field in fields.items()):
        raise HTTPException(422, "Command arguments must match the schema and its limits.")
    bridge = bridges.get(device)
    if not bridge or device not in online:
        raise HTTPException(409, "The device is offline.")
    command_id = "c-" + secrets.token_hex(8)
    try:
        await bridge.send_json({"type": "command", "id": command_id, "name": command.name, "args": command.args})
    except (WebSocketDisconnect, RuntimeError, OSError) as exc:
        raise HTTPException(409, "The bridge disconnected while sending. Check the device before trying again.") from exc
    return {"id": command_id}


async def broadcast(device, message):
    payload = {**message, "device_id": device}
    for socket, token in list(dashboards.items()):
        user = actor(token)
        try:
            if user is None:
                await socket.close(code=1008)
                dashboards.pop(socket, None)
            elif role(user, device):
                await socket.send_json(payload)
        except (WebSocketDisconnect, RuntimeError, OSError):
            dashboards.pop(socket, None)


async def notify_access(username):
    for socket, token in list(dashboards.items()):
        user = actor(token)
        if user and user["username"] == username:
            try:
                await socket.send_json({"type": "access_changed"})
            except (WebSocketDisconnect, RuntimeError, OSError):
                dashboards.pop(socket, None)


@app.websocket("/ws/live")
async def live(socket: WebSocket):
    token = socket.cookies.get("janus_session")
    origin = socket.headers.get("origin")
    if actor(token) is None or (origin and origin not in {"http://" + socket.headers["host"], "https://" + socket.headers["host"]}):
        await socket.close(code=1008)
        return
    await socket.accept()
    dashboards[socket] = token
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        dashboards.pop(socket, None)


def evaluate(device, timestamp, data):
    alerts = []
    for row in db.execute("SELECT * FROM rules WHERE device = ? AND enabled", (device,)).fetchall():
        key = (device, row["id"])
        value = data.get(row["field"])
        if value is None or not OPERATORS[row["op"]](value, row["threshold"]):
            crossed.discard(key)
        elif key not in crossed:
            crossed.add(key)
            values = (device, timestamp, row["field"], row["op"], row["threshold"], value)
            inserted = db.execute("INSERT INTO alerts(device, timestamp, field, op, threshold, value) VALUES (?, ?, ?, ?, ?, ?)", values)
            alerts.append({
                "id": inserted.lastrowid, "device": device, "timestamp": timestamp, "field": row["field"],
                "op": row["op"], "threshold": row["threshold"], "value": value,
            })
    return alerts


@app.websocket("/ws/bridge")
async def connect_bridge(socket: WebSocket):
    if socket.client.host not in ("127.0.0.1", "::1") or socket.headers.get("origin"):
        await socket.close(code=1008)
        return
    await socket.accept()
    device = None
    try:
        while True:
            msg = await socket.receive_json()
            if not isinstance(msg, dict) or not isinstance(msg.get("device_id"), str):
                continue
            identifier = msg["device_id"]
            if device is not None and device != identifier:
                await socket.close(code=1008)
                return
            try:
                schema = device_schema(identifier)
            except HTTPException:
                continue
            device = identifier
            if bridges.get(device, socket) is not socket:
                await socket.close(code=1008)
                return
            bridges[device] = socket
            kind = msg.get("type")
            if kind == "status":
                if msg.get("connected") is True:
                    online.add(device)
                else:
                    online.discard(device)
                await broadcast(device, msg)
            elif kind == "ack":
                await broadcast(device, msg)
            elif kind == "telemetry":
                data = msg.get("data")
                fields = schema["telemetry"]
                if not isinstance(data, dict) or data.keys() != fields.keys():
                    continue
                if any(not valid_value(data[key], field) for key, field in fields.items()):
                    continue
                timestamp = time.time()
                online.add(device)
                last_reading[device] = timestamp
                db.execute("INSERT INTO readings VALUES (?, ?, ?)", (device, timestamp, json.dumps(data)))
                triggered = evaluate(device, timestamp, data)
                await broadcast(device, {"type": "telemetry", "timestamp": timestamp, "data": data})
                for alert in triggered:
                    await broadcast(device, {"type": "alert", "alert": alert})
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        if device and bridges.get(device) is socket:
            bridges.pop(device, None)
            online.discard(device)
            await broadcast(device, {"type": "status", "connected": False})
