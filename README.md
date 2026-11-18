# Janus

A telemetry and control platform for embedded systems.

## The Problem

An embedded system is built from many parts, such as a microcontroller plus the sensors, motors, and other components around it, each with its own inputs and outputs. To see what a system like this is doing, or to change its behavior, developers usually build a custom interface for each device, whether that is a serial monitor script or a one-off GUI. This is inconvenient for a few reasons:

- Every new device means another interface to build and maintain.
- There is no easy way to check on a device, or adjust it, once it is running unattended.
- Sharing a device is risky, because anyone who can watch it can usually control it too.
- Abnormal readings go unnoticed unless someone happens to be watching at the right moment.

## The Idea

Janus lets a device describe itself once. Its firmware sends readings (telemetry) and accepts commands (control) in a small JSON format, declared in a schema. From that schema alone, Janus stores the device's telemetry, shows it live and historically in a web dashboard, sends commands back to the device, flags abnormal readings with alerts, and controls who can view or command each device through roles.

Adding a new device means writing its firmware and its schema, rather than building an entire new interface.

## Run the full local workspace

Install the Python requirements from the repository root and set
`JANUS_OPEN_LOCAL_PREVIEW=1` to open directly to the dashboard on your computer.
This mode opens with administrator access. On PowerShell:

```powershell
python -m pip install -r requirements.txt
$env:JANUS_OPEN_LOCAL_PREVIEW = '1'
python -m uvicorn backend.workspace:app --host 127.0.0.1
```

In a second terminal:

```sh
python bridge/bridge.py --port sim
```

Open [Janus](http://127.0.0.1:8000/). The workspace starts with the Nucleo
simulator registered. Use **Admin** to create users, import other JSON schemas,
grant per-device access, and set alert rules. Viewer accounts can read telemetry
and alerts. Operator accounts can also send commands. History and configuration
are saved in a local SQLite file, with 14 days of history. Set `JANUS_DB` to
choose a database location. Keep the workspace bound to loopback for simulator
demos. Its API implementation is separate from the team's shared backend.

To attach a second simulated device, register a copy of the bundled schema with a
new `device_id`, then start the bridge with `--device-id <new-id>`. The registered
schema determines its display name, fields, bounds, and available commands.

For the [frontend usability test](docs/frontend-usability.md), start without
`JANUS_OPEN_LOCAL_PREVIEW` to use account sign-in. For a new database, set
`JANUS_ADMIN_PASSWORD` to a password of at least eight characters for the
administrator. The default username is `admin`, configurable with
`JANUS_ADMIN_USER`. To use both modes with the same database, set the
administrator password when first starting that database.

## Run the live dashboard without accounts

From the repository root, install the Python requirements, then start the backend
and the bridge in separate terminals:

```sh
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app
```

```sh
python bridge/bridge.py --port sim
```

Open [Janus](http://127.0.0.1:8000/). Select a device, then select a metric
above the chart to plot it. The window selector changes how much recent live
telemetry to display. The browser buffers live readings from the current session.

To see multiple devices with the same schema, run a second bridge:

```sh
python bridge/bridge.py --port sim --device-id sim_2 --schema-id nucleo_tilt_motor
```

A device uses `schemas/<device-id>.json` by default. Specify `--schema-id` when
the filename stem differs. Device status is tracked for the lifetime of the
backend process. This dashboard milestone is for local development.
