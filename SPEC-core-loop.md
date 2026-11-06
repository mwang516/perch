# Spec: Core loop (build step 4)

## Problem Statement

Matthew has confirmed that Jev can tell his desk states apart from the side camera spot (98% activity accuracy across `computer`, `ipad_gaming`, `away` and `other`), but nothing runs live yet. He has no record of how he actually spends his desk time, and the mode engine (step 5) can't be designed or tuned without real data. That data has to pair Jev's camera answers with what the Mac was doing at the same moment, collected over several days of normal use.

## Solution

A program Matthew starts manually from the terminal while at his desk. It holds the iPhone camera (via Continuity Camera) open, decides when a frame is worth sending to Jev, asks Jev the same questions validated in the accuracy test, reads the Mac's own signals at the same moment, and writes one row per observation to a local SQLite database along with a small thumbnail. It prints a line per observation so he can see it working. It does not decide his mode yet; it only collects the data the mode engine will later be tuned against.

## User Stories

1. As Matthew, I want to start the agent with one terminal command, so that running it during development is effortless.
2. As Matthew, I want to stop it with Ctrl+C and have the session closed cleanly, so that the database reflects when it was running.
3. As Matthew, I want the agent to pick the iPhone camera by its name rather than a device number, so that it doesn't accidentally open the MacBook's built-in camera.
4. As Matthew, I want the camera name to live in config, so that I can change it if I rename the phone without touching code.
5. As Matthew, I want the agent to tell me clearly when the configured camera isn't found, and list the cameras it can see, so that I can fix the name quickly.
6. As Matthew, I want the agent to keep running and wait when the camera disappears (phone unlocked, moved, or out of range), so that a dropout doesn't crash it.
7. As Matthew, I want the agent to resume automatically when the camera comes back, so that I don't have to restart it.
8. As Matthew, I want the agent to always work from the newest frame, so that Jev never answers about something stale.
9. As Matthew, I want a heartbeat observation every 20–30 s when nothing changes, so that steady activity is still recorded.
10. As Matthew, I want the agent to sample faster (every 2–3 s for about 30 s) after the scene changes, so that transitions like sitting down or leaving are caught quickly.
11. As Matthew, I want an observation sent right away when the frontmost app changes, so that app switches are captured at the moment they happen.
12. As Matthew, I want an observation sent right away when Mac idle time crosses 60 s, so that the transition from active to idle is recorded.
13. As Matthew, I want scene change measured against the last frame sent to Jev, not the previous frame, so that slow changes still trigger an observation.
14. As Matthew, I want only one Jev request in flight at a time, so that requests don't pile up and answers stay in order.
15. As Matthew, I want triggers that arrive while a request is in flight to be skipped, with the next send using the newest frame, so that there's no queue of old frames.
16. As Matthew, I want SDK retries off, so that a retrying request never answers about an old frame.
17. As Matthew, I want a failed Jev call logged as a failed observation (with the error) rather than retried, so that failures are visible in the data and the next trigger simply sends a fresh frame.
18. As Matthew, I want the live agent to ask exactly the questions validated in the accuracy test, so that live answers match what I measured.
19. As Matthew, I want the question set and frame prep defined in one shared place used by both the accuracy test and the agent, so that they can't drift apart.
20. As Matthew, I want the pinned model `jev-1.14.0` and the images header used on every request, so that answers don't shift silently.
21. As Matthew, I want each observation to record the frontmost app, so that the mode engine can use it later.
22. As Matthew, I want each observation to record the Chrome domain (domain only, never the full URL) when Chrome is frontmost, so that coding sites can be tagged later without storing browsing detail.
23. As Matthew, I want each observation to record seconds since my last keyboard or mouse input, so that the 60 s idle rule can be applied later.
24. As Matthew, I want each observation to record why it was sent (heartbeat, motion, app change, idle crossing), so that I can later judge the sampler and the no-mask experiment.
25. As Matthew, I want each observation to record the scene-change score that triggered it, so that the motion threshold can be tuned from data.
26. As Matthew, I want each observation to record Jev's raw answers (all probabilities, the activity choice and its confidence), so that thresholds can be tuned and replayed offline.
27. As Matthew, I want each observation to record latency, input tokens and the model that answered, so that I can report latency and cost.
28. As Matthew, I want a small thumbnail (about 640×360) saved per observation, so that I can hand-label frames later for the evaluation numbers.
29. As Matthew, I want thumbnails older than 7 days deleted automatically unless I've labeled them, so that photos of me don't pile up on disk.
30. As Matthew, I want a labels table to exist from the start, so that the retention rule can tell which thumbnails to keep.
31. As Matthew, I want each run recorded as a session with start and end times, so that I can tell tracked time from untracked time.
32. As Matthew, I want a run that ended without a clean stop to be detectable as a crash, so that its end isn't mistaken for a deliberate stop.
33. As Matthew, I want a one-line console printout per observation (trigger, Jev answers, latency, tokens, app, idle), so that I can watch it work live.
34. As Matthew, I want a dry-run mode that prints when it would send and why, without calling Jev, so that I can tune the sampler for free.
35. As Matthew, I want the absence of a monitor mask clearly marked as an experiment, so that it's easy to find and revisit later.
36. As Matthew, I want all tunable numbers (intervals, motion threshold, thumbnail size, retention days, camera name) in one config place, so that tuning never requires hunting through code.
37. As Matthew, I want the API key read from `.env`, so that no credential lives in code.
38. As Matthew, I want timestamps stored in UTC, so that the dashboard can convert them consistently later.

## Implementation Decisions

- **Modules.** The agent is split into small modules, tied together by a thin entry point:
  - **Camera:** opens the configured camera by name, runs a background capture thread that keeps only the latest frame, and reports when the camera is unavailable. Handles dropouts by releasing and re-opening.
  - **Sampler:** decides when to send. It holds the last-sent thumbnail and the timing state and returns a trigger reason, or nothing.
  - **Jev client:** prepares the frame, sends one request and returns parsed answers plus latency, tokens and model, or an error.
  - **Mac signals:** frontmost app, Chrome domain, and seconds since last input.
  - **Database:** creates the schema, opens and closes sessions, writes observations, and runs thumbnail retention.
  - **Shared questions and prep:** the question set and frame prep, imported by both the agent and the accuracy test. The accuracy test is changed only to import from here; its behavior is unchanged.
  - **Config:** a single module of constants.
- **Camera selection.** The camera is chosen by its configured name ("Matt Camera" for now). OpenCV can't list device names, and the device order it uses was seen to differ from ffmpeg's listing, so name-to-device resolution must match OpenCV's own ordering. The approach is to enumerate devices through macOS's camera framework and verify the mapping at the first checkpoint. If that mapping proves unreliable, the fallback is to capture through ffmpeg by device name.
- **Frames.** Continuity Camera delivers upright 1920×1080 landscape frames even with the phone mounted vertically, so no rotation is applied. Frames sent to Jev use the same prep as the accuracy test (longest side at most 1568, baseline JPEG quality 90), which gives 1568×882.
- **Sampler behavior.**
  - About twice a second, the latest frame is reduced to a small blurred grayscale thumbnail (about 64×48) and compared with the thumbnail of the last frame sent to Jev.
  - A change score above the threshold triggers `motion` and starts a fast window: sends every 2–3 s for about 30 s.
  - With no other trigger, `heartbeat` fires every 20–30 s.
  - A frontmost-app change triggers `app_change` immediately.
  - Idle time crossing 60 s triggers `idle_crossed` immediately.
  - A trigger that fires while a request is in flight is dropped. The next send always uses the newest frame.
  - All intervals and the threshold are config values and starting points, to be tuned from logs.
- **No monitor mask (experiment).** The change check uses the whole frame. This is deliberately marked as an experiment in config. Trigger reasons and change scores are logged so that, after a few days, it can be judged how often screen content alone caused sends. Mask alternatives that need no per-user setup (body-movement detection, auto-learned busy regions) are noted for later.
- **Jev requests.** Pinned `jev-1.14.0`, the `TypeSafe-Danger-Zone-Images: true` header, and SDK retries disabled. The state is `{"desk": <image>}`. The questions are the final set from the accuracy test:
  - `person_present` (Noul);
  - `tablet_gaming` (Noul);
  - `activity` (Choice: `computer`, `gaming`, `other`, `nobody`);
  - `camera_ok` (Noul);
  - `controllers_out` (Noul).
- **Mac signals.**
  - Frontmost app: the localized name via the workspace API.
  - Idle seconds: seconds since the last keyboard or mouse event via the Quartz event-source API.
  - Chrome domain: read via AppleScript only when Chrome is frontmost, reduced to the domain before storage, and null otherwise. This needs a one-time macOS Automation permission.
  - All signals are read at the moment an observation is sent. They are not sent to Jev.
- **Schema (SQLite, UTC timestamps).**
  - `sessions`: id, start time, end time, end reason (`quit`). A session with no end time is treated as a crash.
  - `observations`: id, session id, timestamp, trigger, change score, status (ok or error), error text, latency ms, input tokens, model version, raw Jev answers as JSON (every Noul probability, plus the activity choice, its probabilities and its confidence), frontmost app, Chrome domain, idle seconds, thumbnail path.
  - `labels`: observation id, true mode. It's empty for now and exists so retention can keep labeled thumbnails.
  - Columns for the fused mode and smoothed scores are not added in this step; the mode engine adds them in step 5.
- **Thumbnails.** About 640×360 JPEG, one per observation, saved to a local folder. A retention pass deletes thumbnails older than 7 days whose observation has no label. It runs at startup and periodically while running.
- **Sessions.** One session per run of the program. A clean stop (Ctrl+C) writes the end time with reason `quit`. Camera dropouts don't end the session in this step; the session and lifecycle rules (camera presence, sleep and resume) are step 6.
- **Dependencies.** OpenCV is already present. The macOS signal and camera-enumeration APIs need the relevant PyObjC framework packages. No test runner is added.
- **Credentials.** `TYPESAFE_API_KEY` is read from `.env`.

## Testing Decisions

- No automated tests in this step, by decision. Verification is a series of manual checkpoints, each run and confirmed by Matthew before the next piece is built:
  1. **Capture:** the agent finds the configured camera by name, holds it open for a long stretch, survives a dropout (phone unlocked and relocked), and resumes. The printed output confirms which device was opened.
  2. **Sampler (dry run, no Jev calls):** sitting, moving, leaving, switching apps and going idle each print the expected trigger at about the expected interval.
  3. **Jev live:** answers print per observation and look sensible for what Matthew is doing. Latency and tokens are in line with the accuracy test (about 150 ms, about 4,400 tokens).
  4. **Signals and database:** rows appear with all fields filled; the Chrome domain appears only when Chrome is frontmost; thumbnails are written; a clean stop closes the session.
- A good check exercises behavior Matthew can observe: console output, database rows, files on disk. It doesn't inspect internals.
- Prior art: the accuracy test script is the reference for request shape, frame prep and the per-frame console line.

## Out of Scope

- The mode engine: fusion rules, smoothing, switching and mode transitions (step 5). This includes the provisional cutoffs (`tablet_gaming` about 0.5, `controllers_out` 0.5).
- The interval used while in `away`, because it depends on modes existing.
- Session and lifecycle handling: camera presence defining sessions, sleep and resume detection, reopening the camera after wake, dormancy when the camera is missing (step 6).
- Starting at login, starting when the camera appears, and the menu bar toggle.
- The dashboard, gestures, the labeling UI and evaluation reporting.
- The daily token budget guard.
- A monitor mask or any of its user-agnostic alternatives.
- Automated tests and a test runner.
- Distribution to other users, including per-user question setup.

## Further Notes

- **The iPhone 13 isn't verified yet.** The Continuity Camera and OpenCV checks so far used Matthew's main iPhone, because he's travelling. The iPhone 13 still needs to show up in Photo Booth and pass the camera check once he's home.
- **Possible name clash.** If the iPhone 13 is also named "Matt", both phones appear as "Matt Camera" whenever both are locked and still near the Mac. If that happens, rename one phone and update the config name.
- **Framing check.** Continuity's landscape view differs from the portrait test clips that produced the 98% result. Once the phone is mounted on the shelf, confirm that the desk, the iPad spot and the chair are all in frame.
- **`controllers_out`.** It has no false positives across 48 frames. The "yes" side is assumed to work and can be checked from logged probabilities during a real gaming session.
- **Expected cost.** About 4,400 input tokens per request, about $0.00018 per observation, roughly a few cents per hour depending on how much motion triggers fast sampling.
- **Connection errors.** Occasional SSL errors were seen in about 3% of test requests. They're logged as failed observations, and their rate in the logs is worth watching.
- **Platform.** The venv runs Python 3.14 on macOS. Camera permission is granted to the app that launches the agent (currently Cursor's terminal), so use the same app consistently.
