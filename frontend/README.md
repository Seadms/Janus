# Janus dashboard

From the repository root, install the dependencies and start the server:

```sh
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app
```

Start the simulator in a second terminal:

```sh
python bridge/bridge.py --port sim
```

Open [Janus](http://127.0.0.1:8000/). The device list uses `GET /api/devices`
and live readings arrive over `/ws/live`. Select a metric to plot it.

To run a second simulator against the same schema:

```sh
python bridge/bridge.py --port sim --device-id sim_2 --schema-id nucleo_tilt_motor
```

The current API supports the live dashboard. Sign-in, history, alerts, commands
with roles, and administration screens are in the frontend. Their integration
will follow as the shared backend adds the corresponding endpoints.
