# Computer-Use Harness

A desktop application that takes a natural-language instruction (e.g. *"Play music in iTunes"*) and autonomously operates the GUI — locating and launching apps, moving the cursor, clicking, typing — by looping an open-source Vision-Language Model (VLM) over screenshots of the live desktop.

---

## High-Level Concept

One loop, one context, one model. Based on the architecture described in **UI-TARS** (Qin et al., 2025):

```
        ┌──────────────────────────────────────────────────────────┐
        │                      AGENT LOOP                           │
        │                                                            │
        │   screenshot ──► THOUGHT ──► ACTION ──► EVALUATE ──┐      │
        │        ▲                                            │      │
        │        └────────────── redo / next step ◄───────────┘      │
        └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼ (tool calls)
                    ┌──────────────────────────┐
                    │   MCP SERVER "computer"   │
                    │  screenshot · open_app    │
                    │  click · drag · type      │
                    │  key_press · scroll       │
                    │  finished · call_user     │
                    └──────────────────────────┘
                                   │
                              Real OS (macOS)
```

Each step:
1. **Screenshot** — capture current screen via the MCP `screenshot` tool.
2. **Thought** — the VLM reasons explicitly: what's on screen, did the last action work, what to do next. Task decomposition, milestone tracking, and failure detection all happen *here*, as reasoning, not as separate agents.
3. **Action** — the VLM emits one MCP tool call grounded in that thought.
4. **Evaluate** — the harness diffs pre/post screenshots to check objectively whether the action had the expected effect.
5. **Redo / continue** — if evaluation shows no change, the next thought is framed as a *reflection* on the failed action. If it succeeded, the loop continues. The loop ends when the model calls `finished`, `call_user`, or a step/time limit is hit.

---

## Project Layout

```
comp-use-harness/
├── backend/
│   ├── server.py                              # FastAPI + WebSocket server (port 7123)
│   ├── logs/                                  # Per-run log files (run-YYYYMMDD-HHMMSS-<id>.log)
│   ├── requirements.txt
│   └── src/computer_use_harness/
│       ├── agent_loop.py                      # Single continuous agent loop (core)
│       ├── vlm_client.py                      # VLM API client — thought extraction + tool calling
│       ├── mcp_server.py                      # MCP "computer-control" tools (real OS actions)
│       ├── session_store.py                   # SQLite session + step persistence
│       └── orchestrator.py                    # (legacy) multi-agent DAG — kept for reference
│
├── frontend/
│   └── src/renderer/src/
│       ├── App.jsx                            # Root component
│       ├── hooks/useTask.js                   # WebSocket task streaming hook
│       ├── lib/api.js                         # HTTP + WebSocket API client
│       └── components/
│           ├── Stream.jsx                     # Flat step feed (thought + action + reflection)
│           └── StepEntry.jsx                  # Individual step row
│
└── architecture.md                            # Full design spec
```

---

## What's Implemented

| Component | Status | Notes |
|---|---|---|
| **Agent loop** (`agent_loop.py`) | ✅ Real | Single continuous perception-thought-action-evaluate loop per UI-TARS. |
| **VLM client** (`vlm_client.py`) | ✅ Real | OpenAI-compatible API. Extracts `<think>…</think>` as `thought`. Heuristic fallback when no VLM configured. |
| **MCP server** (`mcp_server.py`) | ✅ Real | `open_app` (macOS `open -a`), `click`/`drag`/`type`/`key_press`/`scroll` (`pyautogui`), `screenshot` (`mss`). |
| **Evaluate step** (`agent_loop.py`) | ✅ Real | Perceptual diff (32×32 greyscale MAD) on pre/post screenshots. |
| **Reflection loop** (`agent_loop.py`) | ✅ Real | Up to `REFLECTION_CAP=3` consecutive retries with reflection framing before giving up. |
| **Coordinate rescaling** (`agent_loop.py`) | ✅ Real | VLM sees 672-px max-edge images; coordinates are multiplied by `1/scale` before executing. |
| **Per-run logs** (`server.py`) | ✅ Real | Every `harness.*` log line written to `logs/run-<id>.log`. |
| **Session store** (`session_store.py`) | ✅ Real | SQLite; all steps (including thoughts) persisted per session. |
| **Desktop shell** (Electron + React) | ✅ Real | Live step feed showing thoughts, actions, and reflections in one flat list. |
| **SoM / accessibility overlays** | 🔲 Planned | `screenshot_with_marks` tool for coordinate-free clicking. |
| **Settle detection** | 🔲 Planned | Perceptual-hash polling before returning a screenshot frame. |

---

## Quick Start

**1. Start the backend**

```bash
cd backend
pip install -r requirements.txt
python3 server.py
# → backend starting on http://127.0.0.1:7123
```

**2. Configure the VLM** (Settings panel in the app, or edit `vlm_config.json`):

```json
{
  "vlm_base_url": "http://localhost:11434/v1",
  "vlm_model":    "qwen3-vl:8b",
  "vlm_api_key":  "ollama"
}
```

**3. Start the Electron shell**

```bash
cd frontend
npm install   # first time only
npm run dev
```

Type any instruction in the "Do anything." bar and press **⌘↵**.

> **Accessibility permissions** — `open_app` works without them. Mouse/keyboard control requires granting the app Accessibility in **System Settings → Privacy & Security → Accessibility**.

---

## Loop Configuration

Tunables in `agent_loop.py`:

| Constant | Default | Meaning |
|---|---|---|
| `MAX_STEPS` | 30 | Hard step cap before declaring stuck |
| `REFLECTION_CAP` | 3 | Consecutive stalls before giving up |
| `HISTORY_WINDOW` | 8 | Past steps included in VLM context |
| `STEP_PAUSE_S` | 0.35 | Seconds to wait after each action (OS settle) |
| `EVAL_DIFF_THRESHOLD` | 4.0 | Min mean pixel diff to count as "changed" |

Screenshot resolution is capped at **672 px on the longest edge** (`mcp_server.py` `max_edge=672`) — divisible by both 14 and 28, the Qwen-VL patch strides — giving the model a clean patch grid and minimising padding overhead on a 16 GB M1 Pro.

---

## MCP Tool Reference

| Tool | Params | Notes |
|---|---|---|
| `screenshot` | — | Returns base64 JPEG + `{width, height, scale, out_width, out_height}` |
| `open_app` | `name` | macOS `open -a <App>` (no Accessibility needed) |
| `click` | `x, y` | Single left-click |
| `left_double` | `x, y` | Double left-click |
| `right_single` | `x, y` | Right-click (context menu) |
| `drag` | `x1, y1, x2, y2` | Click-and-drag |
| `type_text` | `text` | `pyautogui.typewrite` |
| `key_press` | `keys[]` | e.g. `["cmd", "space"]` |
| `scroll` | `x, y, dx, dy` | `pyautogui.scroll` |
| `move_mouse` | `x, y` | Move without clicking |
| `wait` | `ms` | `time.sleep` |
| `finished` | `summary` | Terminal — ends loop successfully |
| `call_user` | `question` | Terminal — pauses for human input |
| `failed` | `reason` | Terminal — declares task failed |

---

## WebSocket Event Reference

The backend streams these events to the frontend:

| Event | Payload | Description |
|---|---|---|
| `info` | `{vlm_enabled, run_id, message}` | Backend startup info |
| `step` | `{type, label, detail, time, is_reflection?}` | Every loop step (thought / action / reflection / verify) |
| `call_user` | `{question}` | Agent paused, needs human input |
| `complete` | `{status, elapsed_ms}` | Task finished successfully |
| `error` | `{message}` | Server error |

`step.type` values: `thought`, `mouse`, `keyboard`, `screenshot`, `analyze`, `verify`, `error`.  
`step.is_reflection = true` when the step is part of an error-recovery reflection.

---

## Architecture

See [`architecture.md`](./architecture.md) for the full design spec including the UI-TARS reasoning loop, evaluate/reflect mechanics, safety layer, coordinate grounding, and optional multi-agent escalation path.

---

## Reference

Qin, Y. et al. (2025). *UI-TARS: Pioneering Automated GUI Interaction with Native Agents.* ByteDance Seed / Tsinghua University. arXiv:2501.12326.
