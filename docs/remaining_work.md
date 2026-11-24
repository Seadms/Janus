# Remaining work

Everything on `main` works with the real board: the firmware, bridge, simulator, device registration, stored telemetry, live dashboard, login, roles, and alert rules. US numbers refer to the user stories in `docs/requirements.tex`.

Build everything to work with any device. Read field and command names (like `tilt_deg` or `set_motor`) from the device's schema instead of hard-coding them. Test with the simulator.

## Remaining responsibilities by team member

**Daniel**
- Log in with `POST /api/auth/login` instead of `/api/session`. Send the token it returns as `Authorization: Bearer <token>` on every request. `GET /api/auth/me` returns the username and whether they're an admin (US1).
- Command panel: one form per command in the schema, with inputs limited by `min` and `max`. Send with `POST /api/devices/{device_id}/commands`, and show the matching `ack` from `/ws/live` (US6).
- Alert rules: create, list, edit, and delete them with `/api/devices/{device_id}/alerts`. Show alerts as they arrive on `/ws/live` (US11, US13).
- Admin pages: create users (`POST /api/users`), give users a role on a device (`PUT /api/devices/{device_id}/permissions`), and register devices (`POST /api/devices`) (US7, US8, US10).
- Let users drag and resize telemetry charts, show a chart for every field at once, or go back to one.
- Past readings chart with `GET /api/devices/{device_id}/telemetry?start=&end=&fields=`, with `start` and `end` in Unix seconds (US4).
- Alerts list with `GET /api/alerts/history` (US5).
- Remove a device with `DELETE /api/devices/{device_id}`, and remove a user's access with `DELETE /api/devices/{device_id}/permissions/{username}` (US9, US10).
- Hide the command panel from viewers, using the `role` that `GET /api/devices` returns for each device (US6).
- Connect to `/ws/live?token=<token>`.

**Hunter**
- Capacity test: 10 simulated devices at 10 readings per second with 20 dashboards open, checking that everything shows up within 1 second.
- Add a shared token so the backend only accepts known bridges.
- Widen the schema's gyro range to ±260, and keep `tilt_deg` between -180 and 180 in the firmware.
- Sprint reports 2 and 3.

## Running it

In PowerShell, start the backend:

```
pip install -r requirements.txt
$env:JANUS_SECRET_KEY = "any-long-random-string"
$env:JANUS_ADMIN_USER = "admin"
$env:JANUS_ADMIN_PASSWORD = "adminpass1"
python -m uvicorn backend.main:app --reload
```

Register the device once: at http://localhost:8000/docs, log in with `POST /api/auth/login`, click **Authorize** and paste the token, then send the contents of `schemas/nucleo_tilt_motor.json` to `POST /api/devices`.

In a second terminal, start the simulator:

```
python bridge/bridge.py --port sim
```

- Dashboard: http://localhost:8000/
- API: http://localhost:8000/docs. Log in with `POST /api/auth/login`, then click **Authorize** and paste the token.
- For the real board, use `--port COM3` instead of `sim`.

## Where things are

- `schemas/nucleo_tilt_motor.json`: the device schema.
- `bridge/protocol.py`: the messages the bridge sends (`telemetry`, `ack`, `status`).
- `backend/main.py`: devices, stored readings, commands, and the `/ws/bridge` and `/ws/live` connections.
- `backend/auth.py`, `auth_routes.py`, `users.py`, `permissions.py`, `permission_routes.py`: login, accounts, and roles.
- `backend/alerts/`: alert rules and checking readings against them.
- `frontend/`: the dashboard.
