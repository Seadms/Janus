import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Janus")
root = Path(__file__).resolve().parents[1]
app.mount("/frontend", StaticFiles(directory=root / "frontend"), name="frontend")
app.mount("/schemas", StaticFiles(directory=root / "schemas"), name="schemas")

bridges = {}
dashboards = set()

@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(root / "frontend" / "index.html")

class Command(BaseModel):
    name: str
    args: dict = {}

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
