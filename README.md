# Perch

A camera watches my desk. A Python agent on the Mac combines what the camera sees (judged by TypeSafe's Jev model) with what the Mac itself knows (frontmost app, Chrome domain, idle time) to work out what I'm doing, logs it, and shows the day on a local dashboard.

Modes: `computer` (with a `coding` tag), `gaming`, `other`, `away`, `unknown`.

## How it works

```
iPhone (Continuity Camera)
   │ frames
   ▼
agent (desk.py) ── sampler decides when a frame is worth sending
   │                    │
   │ Mac signals        ▼
   │ (app, domain,   Jev: five snap questions about the frame
   │  idle time)        │
   ▼                    ▼
        SQLite: one row per observation + a thumbnail
                        │
                        ▼
   engine (pure function) replays the rows into modes at read time
                        │
                        ▼
              API (FastAPI) → dashboard (React)
```

- **Jev answers camera-only questions.** All fusion with Mac signals happens in code (`engine.py`), so camera-only and fused accuracy can be compared on the same logs.
- **Modes are never stored.** The API replays logged observations through the engine on every request, so changing a threshold re-derives every past day.
- **The sampler is adaptive.** It sends on scene change, app switch, the Mac going idle, or a 25 s heartbeat, with one request in flight at a time and a daily token cap.

## Running it

Requires macOS, Python 3.14 in `.venv`, and Node 20+. Put `TYPESAFE_API_KEY=...` in `.env`.

```bash
.venv/bin/python -m pip install -r requirements.txt
npm --prefix dashboard install
```

Start the agent from a terminal that has camera permission:

```bash
.venv/bin/python desk.py
```

Start the dashboard (API plus the built page on one port):

```bash
npm --prefix dashboard run build
.venv/bin/python -m uvicorn api:app --port 8765
```

Then open http://localhost:8765.

| Page | What it shows |
|---|---|
| Day | Timeline, totals per mode, coding time, the week |
| Label | Hand-label saved frames with keys 1–5; Jev's answers are hidden |
| Accuracy | Fused vs camera-only accuracy, confusion matrices, calibration curves |
| Stats | Latency, cost, failures, and why frames were sent |

The Day and Accuracy pages have an engine-threshold panel for trying values before committing them to `engine.py`.

## Always on

`alwayson/install.sh` builds `~/Applications/Perch.app`, a menu bar app that runs the agent and the dashboard, and registers it to start at login. `alwayson/uninstall.sh` removes it. The agent stays dormant, logging nothing, whenever the camera is missing.

## Gestures

Off by default. `gestures.py` maps MediaPipe hand gestures to actions (play/pause, track skip, mic mute, volume, a keystroke). See the gesture settings in `config.py`.

## Results

To be filled from the Accuracy and Stats pages once real frames are labeled: accuracy per mode, camera-only vs fused, calibration error, latency, and cost per day.

## Files

| File | Role |
|---|---|
| `desk.py` | The agent loop |
| `camera.py`, `sampler.py`, `jev.py`, `signals.py` | Capture, when to send, the Jev call, Mac signals |
| `questions.py` | The Jev questions and frame prep |
| `engine.py`, `replay.py` | Mode engine and replay over logged observations |
| `lifecycle.py` | Sessions, live mode, token budget |
| `db.py` | SQLite schema and writes |
| `api.py`, `dashboard/` | API and dashboard |
| `menubar.py`, `alwayson/` | Menu bar app and installer |
| `gestures.py` | Gesture recognition and actions |
| `fake.py` | Synthetic data for development |
| `HANDOFF.md` | Design decisions and current status |
