# Architecture

The primary interface is `harness-cli`, a C++17 terminal app linked directly to the agent, controller, store, and native adapter. libedit supplies prompt editing and in-process input history. SIGINT cancels active work through the agent cancellation callback; subsequent prompts retain the selected app and bounded recent conversation context. Slash commands inspect sessions and configure the target/model. One-shot mode supports JSON events and meaningful exit codes. The terminal never renders raw control characters from model or application output.

The optional legacy Electron/React UI talks to a C++17 service on loopback port 7123. Boost.Beast handles HTTP and WebSocket framing, Boost.JSON handles JSON, SQLite persists history, and libcurl sends model requests. A small Objective-C++ translation unit bridges AppKit and ApplicationServices. There is no embedded Python interpreter or Python subprocess.

## Request and execution flow

1. `POST /api/tasks` validates a prompt and optional target PID and creates a pending in-memory task.
2. Opening `/api/tasks/{id}/stream` claims it once and starts its worker.
3. The worker acquires the desktop mutex, creates the persistent session and run log, and reads a configuration snapshot.
4. Each agent iteration captures the selected app’s window, performs grid perception when configured, reads accessibility elements, and asks the model for one tool call.
5. The controller validates the call before executing it. After an action, the agent compares 32×32 grayscale thumbnails for visual changes, records compact history, and either continues or reflects.
6. Steps are persisted before being streamed. The session and task terminal status are persisted before the final complete/error event.

Each WebSocket connection has a dedicated Asio event loop. A worker executes blocking model/desktop operations and posts events to that event loop. All WebSocket reads, writes, and closes run on the same event loop. One reader observes disconnects while queued writes are serialized. Cancellation is atomic and checked before each new action, between perception calls, during libcurl transfers, and while settling after an action.

Only one worker can hold the desktop mutex. A second task fails explicitly rather than interleaving keyboard/mouse actions. Duplicate streams cannot rerun a completed or running task. The in-memory task list resets on service restart; persisted sessions remain available.

## Public API

- `GET /`, `GET /json/version`, `GET /api/health`: service information and compatibility probes.
- `GET /api/apps`: running applications and permission readiness.
- `GET /api/config`, `POST /api/config`: model settings. Reads exclude the API key.
- `GET /api/tasks`, `POST /api/tasks`: active/recent tasks and creation.
- `GET /api/sessions`, `GET /api/sessions/{id}`: persistent history.
- `WS /api/tasks/{id}/stream`: starts a pending task and streams `info`, `step`, `computer_frame`, `computer_cursor`, `computer_target`, `call_user`, `complete`, and `error` events.
- `OPTIONS`: frontend CORS preflight.

Step objects preserve `type`, `label`, `detail`, and `time`; live steps may include `is_reflection`. Historical steps include `subtask_id` for compatibility with older sessions. The database retains the original `sessions`, `subtasks`, and `steps` schema. Parameterized queries bind user text and serialize writes; step indexes are allocated inside the insertion statement.

## Model and desktop boundary

Model requests target the configured OpenAI-compatible chat-completions endpoint. The parser accepts structured tool calls and JSON objects in plain text, code fences, or tool-call XML wrappers, including nested/stringified arguments. Invalid output and network/HTTP errors fail the task. The parser does not interpret arbitrary prose as a successful completion.

Screen captures are normalized to the selected window’s logical dimensions. Coordinates are window-local; frames also carry screen origins for the desktop overlay. Accessibility queries are app-scoped. AXPress performs supported semantic clicks; other events use a private Core Graphics source and CGEventPostToPid. There is no global injection fallback or system-pointer warp. Posted events are unverified until subsequent observation; background input support depends on the target app. AppKit handles image encoding, crop operations, marks, and thumbnail comparison. `screencapture` and `open` run via `posix_spawn`, without a shell. Permissions are checked before screen capture/input injection.

Offline mode intentionally supports only explicit single actions. It does not perform random clicks or assume complex goals are completed after a few successful inputs. Dry-run mode validates tools but simulates desktop results; a configured model can still be exercised through the same network and streaming path.

## Build and verification

`backend/Makefile` compiles separate C++/Objective-C++ objects with dependency tracking and links one executable. Boost.JSON is compiled from its installed source header; Boost.Asio/Beast are header libraries. Platform frameworks, SQLite, and curl are linked from macOS. Boost's include prefix is configurable.

`make -C backend test` runs C++ unit checks followed by local HTTP/WebSocket/MCP integration tests. The Node test harness starts a mock model and isolated backend, verifies terminal events and persisted state, cancels a running request, restarts the backend, and cleans up temporary files. Real desktop input and a live vision model are separate manual smoke tests.

The retained DAG helper supports topological ordering, cycle/missing-dependency detection, and status/replan updates. It is not an alternate parallel desktop execution engine. The earlier experimental Python subagent scheduler is retired in favor of the active single-loop architecture.

## Legacy Electron preview ownership

The main renderer owns the task and WebSocket. Electron main relays frame/cursor snapshots to one compact or expanded preview and a separate transparent, click-through cursor window. IPC validates sender and task identity. The preview can request Stop but cannot start another stream. Terminal states, Stop, preview close, owner teardown, and an inactivity timer destroy the desktop pointer. Frames are transient IPC/WebSocket state and are excluded from structured run logs; pre/post screenshots remain separate run artifacts.
