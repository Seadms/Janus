# Remaining work

Everything on `main` works with the real board: the firmware, bridge, simulator, device registration, stored telemetry, live dashboard, login, roles, and alert rules. US numbers refer to the user stories in `docs/requirements.tex`.

Build everything to work with any device. Read field and command names (like `tilt_deg` or `set_motor`) from the device's schema instead of hard-coding them. Test with the simulator.

## Remaining responsibilities by team member

**Japjot (backend)**
- Add an endpoint that returns a device's past readings for chosen fields and a time range (US4).
- Add `DELETE /api/devices/{device_id}` to remove a device (US9).
- Only let admins register or remove devices (US8, US9).
- In `GET /api/devices`, only list the devices the user has a role on (US2).
- Before sending a command, check that it's in the schema and its values are within `min` and `max` (US6).
- Move Samuel's tables from `janus_auth.db` into `janus.sqlite3`, so there's one database.
- Delete readings older than 14 days, once a day.
- On `/ws/live`, only send each user the devices they have a role on. Read the login token from the URL: `/ws/live?token=...`.

**Samuel (roles and alerts)**
- Save each alert when it fires, and add an endpoint that lists a user's alerts (US13, US5).
- Add `DELETE /api/devices/{device_id}/permissions/{username}` to remove a user's access (US10).
- Add an endpoint that returns the logged-in user's role on a device, like `GET /api/devices/{device_id}/permissions/me` (US6).
- Only let admins create, edit, or delete alert rules (US11).

**Daniel (dashboard)**
- Log in with `POST /api/auth/login` instead of `/api/session`. Send the token it returns as `Authorization: Bearer <token>` on every request. `GET /api/auth/me` returns the username and whether they're an admin (US1).
- Command panel: one form per command in the schema, with inputs limited by `min` and `max`. Send with `POST /api/devices/{device_id}/commands`, and show the matching `ack` from `/ws/live` (US6).
- Alert rules: create, list, edit, and delete them with `/api/devices/{device_id}/alerts`. Show alerts as they arrive on `/ws/live` (US11, US13).
- Admin pages: create users (`POST /api/users`), give users a role on a device (`PUT /api/devices/{device_id}/permissions`), and register devices (`POST /api/devices`) (US7, US8, US10).
- Let users drag and resize telemetry charts, show a chart for every field at once, or go back to one.
- Once Japjot and Samuel add their endpoints: past readings chart (US4), alerts list (US5), remove device and remove access (US9, US10), hide the command panel from viewers (US6), and connect to `/ws/live?token=<token>`.

**Hunter (firmware, bridge, and integration)**
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

In a second terminal, register the device (only needed once) and start the simulator:

```
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/devices -ContentType "application/json" -InFile schemas/nucleo_tilt_motor.json
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
