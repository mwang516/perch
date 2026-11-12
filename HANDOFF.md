# Perch — Project Handoff

> This doc is the source of truth for the design decisions. §2 says what is built; where the code and a later section disagree, §2 and the code win. Start here.

---

## 1. What this is

A webcam watches Matthew's desk. A Python agent on his Mac combines **camera judgments from TypeSafe's Jev model** with **macOS signals** (frontmost app, Chrome URL, keyboard/mouse idle time) to work out what he's doing. It then:

- **Logs his desk time** by mode (computer / gaming / away / other), with an optional "coding" tag, into SQLite.
- **Shows a dashboard** of his day (TS/React, localhost).
- **Lets hand gestures trigger one-off actions** (mic mute, music play/pause) via MediaPipe, running locally.

Goal: a genuinely useful personal tool **and a resume project**. Resume strength comes from measured results: accuracy per mode, calibration, camera-only vs. fused ablation, latency, cost per day.

**About Matthew (context for decisions):** 4th-year UBC CS student and software dev intern. Strong in TypeScript/Node, fine with Python. Prefers concise, high-signal communication. Has a 3D printer (Ender 3 V2, ~220×220×250 mm build volume) and does hardware projects.

---

## 2. Status and immediate next steps

**Last updated:** 2026-11-12.

**Built:**

| Step (§15) | State | Where |
|---|---|---|
| 1–2. Camera spot test, accuracy test | Done. Side spot chosen; 98% activity accuracy on the test clips. | `test/` (gitignored) |
| 4. Core loop: capture → sampler → Jev → SQLite | Done and checked on the Mac (checkpoints 1–4 in `SPEC-core-loop.md`). | `desk.py`, `camera.py`, `sampler.py`, `jev.py`, `signals.py`, `db.py`, `questions.py` |
| 5. Mode engine and replay harness | Built and unit-tested against **synthetic data only**. Thresholds are untuned. | `engine.py`, `replay.py`, `tests/` |
| 7. Dashboard: timeline and totals | Built against synthetic data. | `api.py`, `dashboard/` |

**Not built:** the webcam and mount (3), sessions and lifecycle (6), gestures (8), the labeling UI and accuracy page (9), polish (10).

**No real data exists yet.** The camera is not set up at home, so the agent has not collected any days. The camera so far is an iPhone over Continuity Camera ("Matt Camera"), not the USB webcam in §12.

**Differences from the plan below** (the later sections are the original plan and are not all rewritten):

- **Jev questions:** five, not four. `controllers_out` was added. The final wording is in `questions.py`, not §6.
- **Jev client:** retries stay off, except that a dropped connection gets one instant retry (the frame is still fresh). Timeouts and 429s fail the observation. The request timeout is 3 s (`JEV_TIMEOUT_S`). After a failed observation the sampler sends a fresh frame about 2.5 s later (trigger `retry`), once.
- **Failed Jev calls are not `unknown`.** With recent Mac input the frame falls back to the app signal; otherwise it is skipped. The mode becomes `unknown` only after 90 s without usable evidence.
- **Smoothing constant is 30 s, not 20 s.** At 20 s one odd frame at the 25 s heartbeat carries 71% weight and flips the mode alone.
- **`controllers_out` ≥ 0.5 means gaming**, overriding the Mac like `tablet_gaming`. Both cutoffs are 0.5.
- **Modes are derived at read time, not stored.** There is no `modes` table and no fused-mode column. The API replays the day's observations through the engine, so a threshold change re-derives every past day. In-session gaps over 120 s become away segments in `replay.py`.
- **Thumbnails** are kept 7 days (not 14) unless labeled.
- **No monitor mask** in the sampler. This is a marked experiment (`config.py`).

**Known weaknesses:**

- A mode's start lags the real change by roughly 20–40 s, and entering away by over a minute. Segment starts are not backdated.
- The coding tag follows the frontmost app frame by frame, so a glance at a non-coding site splits a coding stretch.
- A retried connection error that succeeds leaves no trace in the database, only a console line.

**Running it:**

```
python desk.py [--dry-run]          # the agent (macOS only)
python fake.py                      # writes a synthetic week to fake.db
pytest tests -q                     # engine, replay and sampler tests
uvicorn api:app --port 8765         # API; reads perch.db, or fake.db when perch.db is absent
cd dashboard && npm run dev         # dashboard on http://localhost:5173 (Node 20+)
```

The engine, replay, fake data, API and dashboard are plain Python and TypeScript and run on any OS. Only the agent needs the Mac. On the Windows PC there is no system Python: prefix Python commands with `uv run --no-project --with <deps>`, and use `dashboard\dev.cmd` to start Vite with Node 22.

**Next steps, in order:**

1. Mount the camera at home and run the agent for a few days to collect real observations.
2. Replay the real logs and tune the engine thresholds (§8). Nothing tuned on `fake.db` counts.
3. Labeling UI and accuracy page (§18), then a tuning page that replays a day with different thresholds (the API already accepts them as query parameters, e.g. `?tau_s=45`).
4. Sessions and lifecycle (§11), then gestures (§10).
5. Buy the webcam, then design the printed mount and the bird cover (§12).

---

## 3. Scope

**In (prototype):**
- Modes: `computer`, `gaming`, `away`, `other`, `unknown`, plus an OS-derived `coding` tag on `computer`.
- Away is **logging only**. No auto-lock, no auto-mute, no auto-pause.
- Gestures (MediaPipe): mic mute toggle, music play/pause. Volume maybe later.
- SQLite logging, a localhost dashboard, sessions, and adaptive polling.
- Runs on the Mac only, started manually during development.

**Later (wanted, not prototype):**
- Physical object controls (e.g. a flipped coaster triggers something), defined by example photos in Jev criteria.
- Webcam plug-to-start plus a menu bar On / Paused / Off toggle.
- Accuracy dashboard page and a labeling UI.
- Remote dashboard access via Tailscale, showing derived data only, never raw frames.

**Explicitly out:**
- Hardware or eating modes (hardware work happens in another room).
- Phone flag or "phone for 10 min" nudges.
- "Where did I leave X" object search.
- "Someone else in frame" detection (the desk doesn't face the door).
- Raspberry Pi (Mac only; refactor later if ever).
- Auto actions on returning from away (unmute, resume, unlock are Matthew's own call).
- Monitor crop or "look closer" screen reading. Screen context comes from the OS, though this could be tried later as an experiment.

---

## 4. Jev (TypeSafe) — key facts

Docs: https://docs.typesafe.ai — especially `/images`, `/primitives`, `/models`. **Image support is experimental ("Dreamer-ready").** Verify details against the docs while building.

### 4.1 What Jev is
- A "System One" model: it returns typed, calibrated probability answers to questions about a `state`. It does not generate text.
- Question types:
  - **Noul:** a yes/no probability from 0 to 1.
  - **Choice:** one of N options, with `choice`, `probabilities`, and `confidence`.
  - **Score:** a position on ordered levels.
  - **Box:** where something is in an image (Jev 1.14+).
- Questions in one request run **in parallel and independently**, so adding questions is nearly free. Keep each one a **snap judgment**.
- Answers are always restricted to the options you supply. Calibration is the selling point: 0.9 should mean about 90%.
- Vendor claims (text tasks): 70–500 ms latency; about 68% agreement with frontier models vs. Opus/Sol at about 73–74%. There are **no published image benchmarks**, which is why our own evaluation matters.

### 4.2 API
- Endpoint: `POST https://api.typesafe.ai/v1/systemone`, with `Authorization: Bearer $TYPESAFE_API_KEY`.
- **Images require the header `TypeSafe-Danger-Zone-Images: true`** on every request containing an image.
- **Pin `model: "jev-1.14.0"`**, not `jev-latest`, so answers don't shift silently when a new release ships.
- Python SDK: `pip install typesafe-sdk`. `Image(Path(...))` creates references automatically. Pass `extra_headers={"TypeSafe-Danger-Zone-Images": "true"}`.
- Use the **direct TypeSafe API**. Gateways (Vercel, OpenRouter) may not pass image assets through.
- **The SDK retries rate-limited (429) requests by default, waiting longer between attempts.** Disable or limit this for the live loop (see §9); otherwise a retrying request holds the in-flight slot and answers about a stale frame.
- **Rate limits are per organization** and shown in the developer console. Check them before choosing polling rates.
- **Context limits:** 64k tokens per request and 32k per question. Images count toward both. One frame plus a few reference photos fits easily.

### 4.3 Images in requests
- Each image goes once in a top-level `assets` map, keyed by a reference string (**use a UUID**). The reference string is written wherever the image belongs: in `state`, in `instructions`, or in `criteria`.
- Every asset must be referenced. Each place a reference appears adds another copy of the image (and its token cost).
- Multipart upload is preferred over base64; base64 adds about 33% to the size.
- Criteria can define options **by example images**. Use this for iPad-gaming reference photos taken from the final mount position.

### 4.4 Limits and image prep
- PNG or JPEG stills only. 16 MiB per file. **Each side 280–1568 px.** Total pixels 78,400 to 2,458,624. 32 MiB request body.
- Images outside the limits are **rejected, not resized**, and any rejected image fails the whole request.
- EXIF is stripped and orientation is **not** applied, so rotate the pixels yourself.
- Prep: rotate upright, scale the longest side to at most 1568, save as a baseline JPEG (quality ~90). Pillow: `ImageOps.exif_transpose` → `thumbnail((1568, 1568))` → `convert("RGB").save(..., "JPEG")`.

### 4.5 Cost
- $0.042 per 1M input tokens; output is free. Images are billed as input tokens.
- **Tokens per image are unpublished.** The estimate is about 1,500, i.e. about $0.00006 per image, so roughly $0.02–0.05 per hour at 5–10 s polling. **Measure it** from `usage.input_tokens` in the accuracy test.

---

## 5. Architecture

```
Mac
├── Capture loop (OpenCV, ~30 fps, keeps the latest frame)
│   ├── every frame → MediaPipe Gesture Recognizer → gesture actions (local, instant)
│   └── adaptive sampler → state builder → Jev API (camera-only questions)
│                                          ↓
│        local signals (frontmost app, Chrome URL, idle time)
│                                          ↓
│                         mode engine (fusion + smoothing + switching)
│                                          ↓
├── SQLite (observations, modes, sessions, gestures, labels)
└── Dashboard (TS/React, localhost) ← reads SQLite (via a small FastAPI layer, or directly)
```

- **Agent:** Python (OpenCV, MediaPipe, pyobjc, typesafe-sdk, sqlite3).
- **Dashboard:** TypeScript/React (Next or Vite), localhost.
- **Hosting:** none. Localhost only.
- **Key design choice:** Jev answers **camera-only** questions. **All fusion with OS signals happens in code** (the mode engine). This is easier to debug, and it lets us measure camera-only vs. fused accuracy from the same logs.

---

## 6. Jev questions (draft — refine after the camera test)

Asked on every sampled frame, all in one request. State: `{"desk": <image ref>}`.

| ID | Type | Instructions (draft) | Criteria (draft) |
|---|---|---|---|
| `person_present` | Noul | "Is a person sitting in the desk chair in `desk`?" | Person physically in the chair, not on a screen |
| `tablet_gaming` | Noul | "Is the person in `desk` playing a game on a tablet (iPad) lying on the desk?" | Later: add reference photos of Matthew playing at the iPad spot, taken from the final mount angle. Partial iPad views are expected because his body may block it. |
| `activity` | Choice | "What is the person at the desk in `desk` doing?" | `computer`: using the computer (keyboard, mouse, or looking at the monitor). `gaming`: playing a game on a tablet, a game controller, or a pen tablet. `other`: at the desk doing something else (phone, eating, resting). `nobody`: no one at the desk. |
| `camera_ok` | Noul | "Does `desk` show a clear, normal, unobstructed view of the desk?" | Catches a bumped or covered camera |

Notes:
- **Noul answers return only a probability (`noul`, 0–1), with no `confidence` field.** Only Choice (and Score) answers include `confidence`. Threshold Noul probabilities directly.
- "Coding" **cannot** be judged by the camera (texting, coding, and chatting all look the same). It's OS-only (§7).
- The purple In Falsus controller halves on the desk are Matthew's DIY rhythm-game controller. He's fine putting them away when not in use. Mac gaming is caught by the OS anyway, so the controller is at most a tiebreaker.

---

## 7. Local signals (macOS)

| Signal | How | Permission |
|---|---|---|
| Frontmost app | `pyobjc`: `NSWorkspace.sharedWorkspace().frontmostApplication().localizedName()` | none |
| Seconds since last keyboard/mouse input | `Quartz.CGEventSourceSecondsSinceLastEventType(...)` | none |
| Chrome active tab URL | `osascript -e 'tell application "Google Chrome" to get URL of active tab of front window'` (store the **domain only**) | Automation (one-time prompt) |

**App → meaning map** (trusted **only if the Mac had input in the last ~60 s**):

| App or condition | Meaning |
|---|---|
| osu!, VMware | gaming |
| Cursor, Terminal or iTerm | computer + `coding` tag |
| Chrome on leetcode.com, github.com (extendable list) | computer + `coding` tag |
| Claude app, Discord, Chrome on other sites, anything else | computer (no tag) |

Why the 60 s rule: when Matthew plays rhythm games on the iPad, Chrome, Discord, or even Cursor may sit frontmost on the idle Mac. An idle Mac means the app signal has no opinion, and the camera decides.

---

## 8. Mode engine — final ruleset

The engine is a **pure function**: `step(state, observation, now) -> (new_state, events)`. It has no I/O, so it's **replayable** over logged observations, which is how thresholds get tuned offline.

### 8.1 Fusion priority (per observation)
0. **Not in a session** → untracked (nothing logged).
1. **Gate:** if `camera_ok` is low, the Jev call failed, or the observation is stale → `unknown`.
2. **Recent Mac input (under a few seconds)** → `away` is impossible.
3. **Camera says nobody is in the chair** (`person_present` low) **and** the Mac has been idle for 60–90 s or more → `away`. Away **requires the camera**; idle time only confirms it.
4. **`tablet_gaming` probability ≥ ~0.8** (Noul has no confidence field; tune the threshold) → `gaming`. **This overrides OS signals**, e.g. Chrome or Cursor frontmost on an idle Mac.
5. **Recent Mac input (under ~60 s) plus a mapped game app** → `gaming`. **Recent input with any other app** → `computer` (plus the `coding` tag if the app is on the coding list).
6. **Otherwise** → Jev's `activity` answer (`computer` / `gaming` / `other`), with `nobody` handled by rule 3.

### 8.2 Smoothing (time-weighted EMA)
Each mode keeps a smoothed score:
```python
alpha = 1 - math.exp(-gap_seconds / TAU)   # TAU ≈ 20 s to start
score[m] += alpha * (fused[m] - score[m])
```
- `exp(-gap/TAU)` is the share of the old score that survives. α is how much the new frame replaces.
- It's consistent under irregular polling: two 10 s gaps equal one 20 s gap. That's why it's exponential rather than `gap/TAU`.
- A single odd frame gets absorbed. A real change wins after a few frames.
- **Reset the scores after a long gap** (resume from sleep).

### 8.3 Switching (hysteresis)
The top-scoring mode replaces the current mode only if:
- its score is ≥ **0.6**,
- it leads the current mode by ≥ **0.15**, and
- the current mode has lasted ≥ **30 s**.

Asymmetry:
- **Entering `away` is slow** (60–90 s of evidence), so bending down to grab something doesn't count.
- **Leaving `away` is instant** on any keypress, or quickly when the camera sees him back. This matters for iPad gaming, where he may not touch the Mac.

All numbers are starting points, to be tuned by replaying logs.

### 8.4 Events and actions
- Mode transitions are logged. **No automated actions fire on mode changes** in the prototype.
- The only actions come from gestures (§10).
- Manual override (later): a gesture or object pins a mode for N minutes.

---

## 9. Adaptive sampler and state builder

**Sampler (decides when to call Jev):**
- About twice a second, shrink the latest frame to a ~64×48 grayscale thumbnail, blur it, and compare it to the **last frame sent to Jev**, not the previous frame. Comparing to the previous frame misses slow changes.
- **Mask out the monitor rectangle** (config JSON) in this change check only. Otherwise videos and scrolling keep the scene "changing" forever. The frame sent to Jev still includes the monitor.

| Trigger | Interval |
|---|---|
| Scene changed beyond threshold | fast: ~2–3 s for the next ~30 s |
| Frontmost app changed, or idle crossed 60 s | immediately |
| Stable (heartbeat) | 20–30 s |
| In `away` | ~45 s |

- **One request in flight at a time.** Skip triggers while busy, then always send the newest frame. No queue.
- **SDK retries off (or capped very low) in the live loop.** A 429 or failed call marks that observation `unknown`; the next trigger sends a fresh frame. Never retry an old frame.
- **Experiment for later:** a short frame history in the state (`frames: [{seconds_ago, frame}, ...]`, as in the docs) might help with ambiguous cases like bending down vs. leaving. It roughly doubles tokens per call, so it isn't the default.
- **Budget guard:** track tokens per day, and stretch intervals near a cap.
- Log the trigger reason (`heartbeat` / `motion` / `app_change` / ...).

**State builder:**
- Prepares the frame (§4.4), assigns a UUID reference, and builds the request from the static question config (§6).
- Camera-only state. OS signals are not sent to Jev. They go to the mode engine.

---

## 10. Gestures (MediaPipe, local)

- Use the **MediaPipe Gesture Recognizer** on every frame. Built-in gestures: Closed_Fist, Open_Palm, Pointing_Up, Thumb_Down, Thumb_Up, Victory, ILoveYou. Custom poses would need Model Maker retraining, or a Jev call when the hand is held still.
- MediaPipe also has an 80-class object detector, 21-point hand landmarks, and 33-point pose, if needed later.
- **Actions (prototype):**
  - **Mic mute toggle:** send Discord's global **Toggle Mute** keybind (Matthew will set one) as a synthetic keystroke (`pyautogui.hotkey(...)` or Quartz). Test that Discord accepts synthetic keys. **Fallback:** OS-level mute with `osascript -e 'set volume input volume 0'`, restoring it on unmute.
  - **Music play/pause:** send the **system play/pause media key**. Matthew uses the **YouTube Music desktop app**, which has no AppleScript support. The media key works for the app and the browser version.
  - Volume: maybe later.
- **False-trigger protection:** hold ~0.5 s, confidence threshold, ~2 s cooldown, and optionally an "arming" pose.
- **Concern:** from a high or side mount, hands are small and seen from above or the side. **Test with the MediaPipe Studio web demo** (Continuity Camera as the webcam) from the mount spot before relying on gestures. If it's unreliable, consider a second small camera near the monitor, or object controls instead.

---

## 11. Sessions, gaps, and app lifecycle

**One rule: a session = the app running AND the designated webcam connected.**

- Write `session_start` when the app starts with the camera present (or the camera is plugged in), and `session_end` on quit, camera unplug, or menu bar "Off".
- **A gap between rows within a session → shown as `away`**, however long. This covers lid closed, power-button sleep, and walking away.
- **Time outside a session → untracked** (quit, unplugged, off).
- **Crash** (no clean `session_end`) → untracked after the last row.
- Gap filling happens **in the dashboard at read time**, not in the agent.

**Sleep and resume:** when the Mac sleeps (lid closed or power button), the process freezes; it doesn't die. On resume, if more than ~2 min passed since the last loop:
- reopen the camera (USB webcams often break after sleep),
- reset the smoothed scores,
- drop any in-flight Jev request.

**Webcam missing** (e.g. MacBook opened at work or school): go dormant, with the camera closed, no Jev calls, and no logging. Poll for the camera to return. Never crash.

**Run modes:**
- **Development:** manual `python desk.py` / Ctrl+C. Early logs will contain false "away" gaps whenever he forgot to start it; that's acceptable.
- **Later:** auto-activate when **the specific webcam** (matched by name or unique ID, *not* the built-in camera or iPhone Continuity Camera) is connected, plus a **menu bar toggle** (`rumps`) for On / Paused / Off. Paused is logged as `paused`. Matthew will turn it off or unplug at night (otherwise the night counts as away).

---

## 12. Hardware

### Camera position (decide via the iPhone test)
Desk layout: desk against the back wall; LG external monitor center-left on a riser; **MacBook on the far-left extension** (it will often be hidden behind Matthew's body, which is fine since Mac usage comes from the OS); keyboard and mouse center; tall white shelf in the back-right corner; short white shelf on the right wall next to the chair. The iPad always sits in the **same spot** when he plays, but his body may block it from some angles.

Candidates:
1. **Right wall, above the short white shelf** (Matthew's idea). A side view, so less blocking by his body. Rigid wall mount. Mount it **high (near the ceiling), angled ~45° down, slightly behind the seated position**.
2. **Back-right corner, high above the tall shelf.** A front-right view: best for hands, the iPad spot, and gestures (palms face the camera). Downsides: his face is in frame, and it looks out into the room.

Pick whichever iPhone clip shows the iPad spot and hands most clearly.

### Webcam
Requirements: a USB UVC webcam that works on macOS; 100°+ field of view (confirm with the iPhone 0.5× vs 1× test); 1080p is enough; lockable exposure; fixed or lockable focus.

Shortlist (from Muse.ai research, Nov 3 2026):
- **ELP IMX291 USB board camera with the 100° no-distortion lens (ELP-SUSB1080P01) — recommended.** It has the same STARVIS sensor as the Arducam at about half the price; it's a bare 38×38 mm board for a printed bracket, with full UVC manual controls. Canadian price unverified (~US$55–70).
- **Arducam 1080P Low Light IMX291, 100°:** same board class, ~$163 CAD at Newegg.ca (slow shipping); Amazon.ca is faster.
- **NexiGo N60:** $41 CAD at Best Buy. A fine budget option, but only ~48° vertical field of view (check the framing) and a fixed 1.5 m cable.
- Razer Kiyo Pro (discontinued; needs Windows for its 103° setting) and Anker C300 (autofocus hunting, AI framing) are less suitable.

**Exposure control on macOS:** OpenCV can't reliably set UVC controls on a Mac, so use a CLI such as `uvc-util` to lock exposure and white balance. The room will be kept bright.

### Cable
The right wall to the MacBook (far left) is probably more than 3 m along the desk's back edge. **Measure it.** Use an **active USB extension** (with a repeater) in the 3–5 m range, or a hub mid-desk. Avoid chains of passive extensions.

### Bird cover (later)
To go with the name, the camera gets a 3D-printed cover shaped like a bird. Ideas so far: the lens is the bird's eye, and the 45° downward mount angle has the bird looking down at the desk. Keep the cosmetic shell separate from the structural bracket, so reprinting or swapping the bird never moves the camera. Design it after the webcam is chosen, since the dimensions depend on it.

### Mount
A custom 3D-printed wall mount. PETG for stiffness (PLA creeps). A board-camera bracket, or a ¼"-20 screw for a finished webcam. Design within the Ender 3 V2's build volume (split into parts if needed). Rigidity matters: the monitor mask and the reference photos assume the camera never moves.

---

## 13. Data model (SQLite, draft)

- `sessions`: id, start_utc, end_utc, end_reason (quit / unplug / off / crash)
- `observations`: id, session_id, ts_utc, trigger, latency_ms, input_tokens, model_version, **Jev raw answers** (all probabilities as JSON), frontmost_app, chrome_domain, idle_seconds, **fused mode**, smoothed scores (JSON), thumbnail_path
- `modes`: session_id, mode, coding_tag, start_utc, end_utc
- `gestures`: ts_utc, gesture, action, success
- `labels`: observation_id, true_mode (for evaluation)

Rules:
- Store **raw Jev answers and the final mode separately**; this enables threshold tuning and the ablation.
- Timestamps in UTC; convert in the dashboard.
- Thumbnails are low-res, auto-deleted after 7 days unless labeled.
- The schema actually in use is in `db.py`: `sessions`, `observations`, `labels`. See §2 for why there is no `modes` table.

---

## 14. Dashboard (TS/React, localhost)

- **Prototype (built):** a timeline of the day; daily totals per mode; computer time split by the coding tag; untracked gaps shown blank and in-session gaps as away.
- **Later:**
  - an accuracy page against hand labels: confusion matrix, calibration curve, camera-only vs. fused comparison;
  - a labeling UI (show a thumbnail, click the true mode);
  - polling, latency, and cost stats.
- Remote viewing (later): Tailscale to localhost. **Never expose raw frames.**

---

## 15. Build order

1. Camera spot test (iPhone).
2. Accuracy test script (§2).
3. Buy and mount the webcam.
4. Core loop: capture → adaptive sampler → Jev → SQLite, no engine yet. Run for a few days.
5. Mode engine (pure, replayable) plus a replay harness; tune thresholds.
6. Sessions and lifecycle (sleep/resume, missing camera).
7. Dashboard: timeline and totals.
8. Gestures (MediaPipe): mic mute and play/pause.
9. Evaluation: labeling UI, accuracy page, README numbers.
10. Polish: menu bar toggle, plug-to-start, printed mount, README with architecture diagram, demo video.

---

## 16. Credentials, permissions, repo hygiene

- **Only credential:** `TYPESAFE_API_KEY` in `.env`.
- **macOS permissions** are granted to **the app that launches Python** (Terminal vs. Cursor's terminal are separate), so pick one and stick with it:
  - **Camera:** webcam (prototype).
  - **Automation:** Chrome URL; System Events (prototype).
  - **Accessibility:** synthetic keystrokes and media keys (gesture phase).
  - Discord's own **Input Monitoring:** global keybinds (gesture phase).
- `.gitignore`: `.env`, `*.db`, `thumbnails/`, raw test videos.

---

## 17. Edge cases and mitigations

| Case | Mitigation |
|---|---|
| A single weird frame | EMA smoothing plus hysteresis |
| iPad gaming with Chrome, Discord, or Cursor frontmost | 60 s idle rule, and `tablet_gaming` overrides OS signals |
| iPad partly hidden by Matthew's body | Mount angle; reference photos showing the partial view; Mac idle plus person present as a hint |
| Bending down or leaning out of frame | Slow away entry (60–90 s) and an idle requirement |
| Returning without touching the Mac (iPad) | Camera-based away exit |
| Lid closed or sleep | Session gap → away; reset on resume |
| Webcam missing (at work or school) | Dormant, no logs, no crash |
| Forgot to start the app (dev phase) | Accepted; logs untrustworthy for that period |
| Camera bumped or covered | `camera_ok` question → `unknown`; recalibrate the mask |
| Jev down, rate-limited, or 400 | `unknown`, never block; validate image size before sending |
| Experimental image API changes | Pin `jev-1.14.0`; wrap the client behind an interface |
| Monitor content triggering motion | Monitor mask in the change detector |
| Discord ignoring synthetic keys | OS-level mic mute fallback |
| Night with the camera still plugged in | Accepted; Matthew turns it off |
| Privacy | Frames go to TypeSafe (retention undocumented outside enterprise). Desk-only framing, thumbnails auto-deleted, Chrome stored as domain only, never expose frames remotely, pause toggle |

---

## 18. Evaluation plan (the resume part)

- Hand-label a few hundred saved thumbnails from real days.
- Report:
  - **accuracy per mode** and a **confusion matrix**;
  - **calibration**: do Jev's 0.9s land about 90% of the time on images? This is unverified by anyone, which makes a good interview story;
  - **camera-only vs. camera + OS fusion** accuracy (an ablation from the same logs);
  - **latency** and **cost per day**;
  - **adaptive vs. fixed polling** (calls per hour at equal accuracy).
- Example resume bullet: *"Built a multimodal desk-context system fusing camera frames (Jev) with OS telemetry; X% mode accuracy at $Y/day."*

---

## 19. Open decisions

- **Camera mount spot** and **field of view**: from the iPhone test.
- **Final Jev question wording** and the iPad reference photos: from the camera test plus the accuracy test.
- **Which webcam** to buy (ELP recommended) and the cable length.
- **Gesture set details:** which built-in gesture maps to mute vs. play/pause; the arming pose.
- **Thresholds:** TAU, 0.6 / 0.15 / 30 s, away timing. Tune with replay.
- **Coding app and domain list:** extend as needed.
- **Thumbnail retention** and labeling workflow.
- **Dashboard contents** beyond the timeline and totals.
