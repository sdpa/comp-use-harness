# Computer-Use Harness — Architecture

A desktop application that takes a natural-language instruction and autonomously operates the GUI by looping an open-source Vision-Language Model (VLM) over screenshots of the live desktop. OS control is exposed as an **MCP (Model Context Protocol) server**, and the model reasons using an explicit **chain-of-thought / System-2 reasoning loop**, based on the approach described in the UI-TARS paper (Qin et al., 2025).

**Default architecture is a single continuous agent loop, not a multi-agent one.** UI-TARS itself is evaluated and deployed as one model running one uninterrupted trace per task — task decomposition, phase transitions, and verification all happen as *reasoning within that one loop*, not as separate spawned processes. A multi-agent orchestrator/sub-agent split is described at the end (§7) as an optional escalation for tasks that genuinely need it.

---

## 1. High-Level Concept

```
        ┌─────────────────────────────────────────────────────────────┐
        │                        AGENT LOOP                            │
        │                                                               │
        │   screenshot ──► THOUGHT ──► ACTION ──► EVALUATE ──┐          │
        │        ▲                                            │          │
        │        └──────────────── redo / next step ◄─────────┘          │
        └─────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ (tool calls)
                     ┌─────────────────────────┐
                     │      MCP SERVER          │
                     │  screenshot · open_app   │
                     │  click · drag · type     │
                     │  key_press · scroll      │
                     │  finished · call_user    │
                     └─────────────────────────┘
                                    │
                              Real OS (macOS)
```

One loop, one running context, one model. Each step:

1. **Screenshot** — capture the current screen via the MCP `screenshot` tool → observation `o_n`.
2. **Thought** — the VLM reasons explicitly before acting: what's on screen, whether the previous action worked, what the next step should be and why. This single reasoning step is where task decomposition, long-term goal tracking, milestone transitions, and failure detection all happen — as *reasoning*, not as separate agents.
3. **Action** — the VLM emits one MCP tool call, grounded in that thought.
4. **Evaluate** — the harness diffs the pre/post-action screenshots and checks the tool's own result, to determine objectively whether the action had the expected effect.
5. **Redo / continue** — if evaluation shows no expected change, the next thought is explicitly a *reflection* on the failed action rather than a fresh attempt with no memory. If it succeeded, the loop continues. The loop ends when the model calls `finished`, `call_user`, or a step/time limit is hit.

---

## 2. Core Components

### 2.1 The Agent Loop (`agent_loop.py`)
A single Python `asyncio` loop owning the whole task context. Responsibilities:
- Maintains **task state**: the original instruction, full `(thought, action, result, eval_ok)` history, step count, consecutive-reflection count.
- Calls the **MCP server** for screenshots and tool execution.
- Calls the **VLM** with the instruction + compact history text + current screenshot.
- Parses the response into `{thought, action}`.
- Runs the **Evaluate** check (§2.5).
- Applies stopping/safety policy: `MAX_STEPS=30`, `REFLECTION_CAP=3`, always-available kill.

Key tunables (all in `agent_loop.py`):

| Constant | Default | Meaning |
|---|---|---|
| `MAX_STEPS` | 30 | Hard step cap |
| `REFLECTION_CAP` | 3 | Consecutive stalls before giving up |
| `HISTORY_WINDOW` | 8 | Past steps sent to VLM |
| `STEP_PAUSE_S` | 0.35 | Post-action wait for OS to settle |
| `EVAL_DIFF_THRESHOLD` | 4.0 | Mean pixel diff (32×32 greyscale) to count as "changed" |

### 2.2 MCP Server: "computer-control" (`mcp_server.py`)
The single gateway to the real OS. Exposes the UI-TARS unified action space as MCP tools:

| Tool | Params | Notes |
|---|---|---|
| `screenshot` | `region?` | Returns base64 JPEG + `{width, height, scale, out_width, out_height}` |
| `open_app` | `name` | macOS `open -a` (no Accessibility needed) |
| `click` | `x, y` | Single left-click (`pyautogui`) |
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

Centralising all OS access behind one MCP server is worth keeping regardless of loop architecture — it's the natural place to enforce safety (§2.7) and means the same "computer" server can be pointed at by a completely different client (Claude Desktop, a different model) without touching OS-control code.

### 2.3 Perception (`mcp_server.py` → `screenshot`)
Implemented inside the MCP server's `screenshot` tool:
- **Downscaling**: images are resized so the longest edge = **672 px**, preserving aspect ratio. 672 is divisible by both 14 and 28 (Qwen-VL patch strides), giving the model a clean patch grid with no padding overhead — the sweet spot on a 16 GB M1 Pro.
- **Scale factor**: the result includes `scale` (= `max_edge / native_long_edge`). The agent loop multiplies VLM coordinate outputs by `1/scale` before executing clicks.
- **`screenshot_with_marks`** variant: runs a UI element detector (OmniParser or OS accessibility tree) and returns `marks: [{id, label, bbox}]`, so the model can act by mark ID instead of guessing raw coordinates.
- **Settle detection** (planned): poll for perceptual-hash stability before returning a frame.

### 2.4 VLM Reasoning Engine (`vlm_client.py`)
Per UI-TARS's `(observation, thought, action)` format, each step's model output is parsed into:
```python
VLMDecision(
    tool_name = "click",
    args      = {"x": 177, "y": 23},
    thought   = "The URL bar is visible at the top. I'll click it to focus it before typing.",
)
```

**Thought extraction**: Qwen3-VL emits `<think>…</think>` blocks before its tool call. These are captured as `decision.thought` (shown in the UI as the reasoning step) rather than being stripped silently.

**History format**: past steps are sent as compact text (no images — only the current screenshot is ever in the VLM's context). Each line:
```
Step 3: [URL bar is focused] → type_text(text='weather') ✓ eval:✓
```

**Reflection framing**: when `is_reflection=True`, the user turn is prefixed with an explicit callout:
```
REFLECTION: Your last action `type_text(text='weather')` did NOT produce a visible change.
Carefully examine the current screenshot and try a different approach:
```

The single thought at each step is expected to naturally exhibit whichever of UI-TARS's five reasoning patterns is relevant:

| Pattern | In-loop appearance |
|---|---|
| **Task Decomposition** | Early thought: "This needs two things — open the app, then hit play." Stays internal to the model's plan, not a separate spawned task. |
| **Long-term Consistency** | Each thought re-grounds in the original instruction + history, preventing drift over a long run. |
| **Milestone Recognition** | "App is now open — moving to playback." This *is* the phase transition; no hand-off required. |
| **Trial and Error** | Before uncertain clicks, thought states a hypothesis; model may re-screenshot before committing. |
| **Reflection** | Triggered by the Evaluate step; explicitly framed in the next prompt. |

**Model choice**: UI-TARS (2B/7B/72B) is the most direct fit (natively trained for `(thought, action)` output). Qwen2.5-VL/Qwen3-VL work well with few-shot prompting. Serve via Ollama, vLLM, or TGI.

### 2.5 Evaluate (Objective Success Check)
After each action, the harness — not the model — checks whether the action had the expected effect:
1. **Tool-level check**: did the MCP tool return `{ok: true}`?
2. **Visual diff**: compare 32×32 greyscale thumbnails of pre/post screenshots (mean absolute pixel difference). If `diff < EVAL_DIFF_THRESHOLD` (default 4.0), the screen hasn't meaningfully changed.
3. **Non-visual exemptions**: `screenshot`, `wait`, `move_mouse`, `open_app` are always considered successful if the tool reported ok.

If Evaluate says no change, the next loop iteration is explicitly a reflection, not a fresh memory-less attempt.

### 2.6 Reflection (Error Recovery, In-Loop)
When Evaluate signals no expected change:
1. The user-turn message is prefixed with an explicit reflection callout (§2.4).
2. This produces a corrected `(reflective thought, corrected action)` pair.
3. After `REFLECTION_CAP=3` consecutive stalls, the loop stops and emits a `task_failed` event.

### 2.7 Safety & Guardrails (at the MCP server)
- Action allow-list/deny-list for sensitive apps.
- Confirmation gate for destructive-looking calls (delete, send, purchase, submit).
- Dry-run mode: logs intent only, never touches OS.
- Loop breakers: `MAX_STEPS`, `REFLECTION_CAP`, repeated-identical-action detection.
- Global emergency-stop hotkey registered by the server process.

### 2.8 Desktop Application Shell (Electron + React)
- **Prompt input** + a **flat live step feed**: each step shows either a thought (collapsed, italic, with 💭 icon) or an action (icon + label + detail + timestamp).
- Reflection steps are tinted amber (`step-reflection` CSS class) to make error-recovery visible.
- When the agent calls `call_user`, a **human-input banner** appears with the question.
- Pause / Resume / Stop.

### 2.9 Logging (`server.py`)
- Every `harness.*` log line (screenshots, VLM calls, tool executions) is written to a per-run file: `backend/logs/run-YYYYMMDD-HHMMSS-<task_id_prefix>.log`.
- The `run_id` is included in every WS `info` event so the frontend can display it.
- Full step trace persisted to SQLite via `SessionStore`.

---

## 3. End-to-End Flow (Example: "Play music in iTunes")

All within **one** loop, one context:

1. `screenshot` → *thought*: "No iTunes window visible. Need to launch it." → `open_app("iTunes")`.
2. **Evaluate**: tool ok; screenshot shows iTunes loading → continue.
3. `screenshot` → *thought*: "iTunes open showing library view, no track playing — launch done. Play button is top-left transport control." → `click(143, 88)`.
4. **Evaluate**: diff shows play icon switched to pause/waveform active → continue.
5. `screenshot` → *thought*: "Waveform active, playback confirmed." → `finished("Started playback in iTunes.")`.
6. Loop ends, reports success to the UI.

If step 4's eval showed no change:
- `consecutive_reflections → 1`
- Next thought is reflection-framed: "Click had no effect — this may not be the play control. Trying Controls > Play from the menu bar."
- If still stuck after 3 reflections → `task_failed`.

---

## 4. Suggested Tech Stack Summary

| Layer | Tool/Library |
|---|---|
| Agent loop | Python `asyncio`, single process (`agent_loop.py`) |
| MCP server ("computer-control") | Official MCP SDK, `stdio` transport, UI-TARS unified action space |
| VLM serving | Ollama / vLLM / TGI; model: Qwen3-VL or UI-TARS |
| Screenshot capture | `mss`, resized with PIL/Pillow to 672-px max edge |
| UI element detection (SoM) | OmniParser, or native accessibility APIs (inside MCP server) |
| Input simulation | `pyautogui` (inside MCP server) |
| Desktop shell | Electron + React |
| Storage/logging | SQLite (`session_store.py`) + per-run log files |

---

## 5. Key Design Risks & Mitigations

- **Coordinate grounding accuracy** → SoM overlays; prefer GUI-specialized models (UI-TARS, ShowUI); 672-px input resolution for clean patch grid.
- **Context growing too long** → `HISTORY_WINDOW=8` caps how many past steps are sent; no images in history (compact text only).
- **Non-causal thoughts** → thought-before-action ordering enforced in prompt; Evaluate provides an objective external check.
- **Infinite reflection loops** → `REFLECTION_CAP=3` hard cap, then `task_failed`.
- **Destructive actions** → allow-list, confirmation gate, dry-run mode, `call_user` escalation — all at the MCP server boundary.

---

## 6. Suggested Build Order (MVP → v1)

1. Build `computer-control` MCP server standalone; validate manually (Claude Desktop or test script).
2. Wire single agent loop with **plain action output, no thought** — one hardcoded task end-to-end.
3. Add `{thought, action}` schema and Evaluate step with visual diffing.
4. Add reflection loop — test against a deliberately unresponsive UI element.
5. Add SoM/accessibility overlay for better grounding.
6. Add safety layer at MCP server (allow-list, stop hotkey, dry-run).
7. Build Electron UI with live flat step feed (thought + action + reflection).
8. Add per-run logging and session replay.
9. Test across a broader set of real single-app tasks before considering §7.

---

## 7. Optional Escalation: Orchestrator + Sub-agents

Keep the single loop as the default. Only reach for a multi-agent split for these specific cases:

- **Real parallelism**: the instruction requires operating two independent apps simultaneously (e.g. "open Spotify and start music *and* open Notes and jot today's date") — run two concurrent single-loops rather than one context-switching.
- **Context length bottleneck**: an extremely long, many-step task where even truncated history degrades reasoning — split into sequential phases with fresh, scoped contexts.
- **Deliberate cost/latency tiering**: cheap/fast model for mechanical phases (app launching), large model only for ambiguous UI navigation.

If you reach this point, the shape is: a thin Orchestrator that decomposes into phases, spawns one single-loop (`AgentLoop`) per phase with its own MCP client session, and stitches results together. Each spawned loop is *exactly* the loop in §1–§2, scoped to a narrower goal. The `orchestrator.py` and `sub_agent.py` files in the repo are the legacy implementation of this pattern.

---

## Reference

Qin, Y. et al. (2025). *UI-TARS: Pioneering Automated GUI Interaction with Native Agents.* ByteDance Seed / Tsinghua University. arXiv:2501.12326 — source of the unified action space, the `(observation, thought, action)` trace format, the five System-2 reasoning patterns, and the Reflection Tuning error-correction approach. Notably, the paper's own agent is a single continuous model loop, not a multi-agent system.
