import sqlite3
import uuid
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field


DB_PATH = Path("janus.sqlite3")
bridges = {}
dashboards = set()


@asynccontextmanager
async def lifespan(app):
    with closing(sqlite3.connect(DB_PATH)) as db, db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY,
                schema_json TEXT NOT NULL
            );
        """)
    yield


app = FastAPI(title="Janus", lifespan=lifespan)


class NumericField(BaseModel):
    type: Literal["number"]
    label: str
    unit: str
    min: float = Field(strict=True, allow_inf_nan=False)
    max: float = Field(strict=True, allow_inf_nan=False)


class DeviceCommand(BaseModel):
    label: str
    args: dict[str, NumericField]


class DeviceSchema(BaseModel):
    device_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str
    rate_hz: float = Field(gt=0, strict=True, allow_inf_nan=False)
    telemetry: dict[str, NumericField] = Field(min_length=1)
    commands: dict[str, DeviceCommand]


class Command(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)


@app.post("/api/devices", status_code=201)
async def register_device(schema: DeviceSchema):
    fields = list(schema.telemetry.values())
    for command in schema.commands.values():
        fields.extend(command.args.values())
    if any(field.min > field.max for field in fields):
        raise HTTPException(status_code=422, detail="Field min must be at or below max")

    with closing(sqlite3.connect(DB_PATH)) as db, db:
        result = db.execute(
            "INSERT INTO devices VALUES (?, ?) ON CONFLICT(device_id) DO NOTHING",
            (schema.device_id, schema.model_dump_json()),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=409, detail="Device is already registered")
    return {"device_id": schema.device_id}


async def broadcast(msg: dict):
    for ws in list(dashboards):
        try:
            await ws.send_json(msg)
        except Exception:
            dashboards.discard(ws)

@app.websocket("/ws/bridge")
async def bridge_socket(ws: WebSocket):
    await ws.accept()
    device_id = None
    try:
        while True:
            msg = await ws.receive_json()
            device_id = msg.get("device_id", device_id)
            if device_id is not None:
                bridges[device_id] = ws
            await broadcast(msg)
    except WebSocketDisconnect:
        if device_id is not None and bridges.get(device_id) is ws:
            del bridges[device_id]
            await broadcast({"type": "status", "device_id": device_id, "connected": False})

@app.websocket("/ws/live")
async def live_socket(ws: WebSocket):
    await ws.accept()
    dashboards.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        dashboards.discard(ws)

@app.get("/api/devices")
async def list_devices():
    return {"devices": sorted(bridges)}

@app.post("/api/devices/{device_id}/commands")
async def send_command(device_id: str, command: Command):
    ws = bridges.get(device_id)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"device {device_id} is not connected")
    msg = {"type": "command", "id": f"c-{uuid.uuid4().hex[:8]}", "name": command.name, "args": command.args}
    await ws.send_json(msg)
    return {"id": msg["id"]}
