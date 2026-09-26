# Computer-Use Harness

A native **C++17 terminal agent for macOS**. Describe a computer task, watch its actions stream into the terminal, and enter follow-up requests. It uses screenshots, app-scoped accessibility, and targeted input, with SQLite session history.

## Build and run

Requires macOS, Xcode Command Line Tools (`xcode-select --install`), and Boost 1.75+. SQLite, libcurl, libedit, and the platform frameworks ship with macOS. No Python or Electron runtime is needed.

```sh
brew install boost
make -C backend -j4
./backend/build/harness-cli
```

For Intel Macs or a custom Boost install, pass `BOOST_PREFIX="$(brew --prefix boost)"` to make.

```sh
# Safe simulated task, without desktop input:
./backend/build/harness-cli --dry-run -p "open Safari"
# Script-friendly events:
./backend/build/harness-cli --dry-run -p "open Safari" --json
# Select an already-running application:
./backend/build/harness-cli --target 1234
```

In VS Code choose **Terminal → Run Task → Harness: run**. It builds and starts the CLI in an interactive terminal. Dependencies already installed for this repository are reused.

`--db PATH`, `--config PATH`, and `--logs PATH` override storage paths; defaults resolve from the executable's repository location. `--dry-run` simulates desktop actions, but configured model requests still run. Without a model endpoint, offline mode supports exact single commands such as `open Safari`, `type Hello`, `screenshot`, and `wait 100`.

The HTTP/MCP binary remains available as `./backend/build/harness` for integrations. The default VS Code workflow no longer starts it or Electron.

## Model configuration

Use `backend/vlm_config.json`, `/model NAME`, or environment variables:

```sh
export COMPUTER_USE_VLM_BASE_URL=http://localhost:11434/v1
export COMPUTER_USE_VLM_MODEL=qwen2.5-vl:7b
export COMPUTER_USE_VLM_API_KEY=ollama
./backend/build/harness-cli
```

The endpoint must implement `POST /chat/completions` relative to the configured base URL and accept image messages. Nonempty config-file values take precedence over environment variables. Config changes apply to the next task. The API key is never returned by `GET /api/config`; saved config files have owner-only permissions.

The agent physically crops a screenshot into a 4×4 grid for perception, then requests one action using the screenshot, grid descriptions, accessibility elements, and the last eight actions. It stops on completion, failure, human-input requests, three consecutive stalls, or 30 actions. Model/network failures are reported rather than silently triggering unrelated desktop actions.

## macOS permissions

For real desktop control, grant the launching terminal **Screen Recording** and **Accessibility** access under System Settings → Privacy & Security. Restart the backend after changing permissions. Select a running app with `/apps` and `/target PID`, or ask the agent to open one. Screenshots and action coordinates use logical points relative to the selected app’s visible window, including on Retina displays. Minimized or hidden windows must be made visible first; `get_screen_info` reports all active displays.

The macOS adapter uses native keyboard, mouse, accessibility, and image APIs, plus the system `screencapture` and `open` executables with explicit argument arrays. It does not execute model-provided shell commands. Run one live client at a time. Ctrl+C cancels subsequent actions and in-flight model requests; an OS action already in progress may finish.

## Terminal workflow

Enter a task at `compuse ›`. Arrow keys edit and recall commands within the current process. Follow-up requests retain bounded recent task context and the selected app; `/new` clears both. Each task saves its status and steps to SQLite. No HTTP server, Node runtime, or Electron is required to run the CLI.

- `/apps` lists running applications and permission readiness.
- `/target PID` chooses an app; `/target 0` clears the selection.
- `/model` displays the model and endpoint; `/model NAME` saves a model name.
- `/history` lists saved tasks; `/show ID` reads one.
- `/help` lists commands; `/quit` or Ctrl+D exits.
- Ctrl+C during a task cancels further actions and returns to the prompt. An OS action already in progress may finish.

Use `-p "instruction"` for a single task. Add `--json` for newline-delimited events; screenshots are saved as run artifacts rather than printed. Exit codes are 0 for success, 1 for failure, and 130 for cancellation. `NO_COLOR=1` disables terminal styling. Piped input accepts one instruction or slash command per line.

The CLI uses the existing app-scoped accessibility and per-PID input adapter. Background input support varies by app; posting input does not prove it was handled. There is no global input fallback. The CLI does not launch the Electron preview or cursor overlay. The old Electron client remains an optional legacy client for the HTTP service; do not run simultaneous live tasks from different clients.

## Verification

C++ and Objective-C++ formatting uses the repository's `.clang-format` (LLVM
style, two-space indentation, 80 columns, and a blank line between function
definitions). `SeparateDefinitionBlocks: Always` enforces function spacing,
including inline class methods and Objective-C++ definitions. Linting uses Clang compiler warnings
and its path-sensitive static analyzer; warnings and analyzer findings fail the
command. These tools come with Xcode, with no additional runtime dependency.

```sh
make -C backend format        # Apply formatting to sources, headers, and tests
make -C backend format-check  # Check formatting without changing files
make -C backend lint          # Compiler diagnostics and static analysis
make -C backend check         # Both read-only checks, suitable for CI
```

Override `CLANG_FORMAT=/path/to/clang-format` or `CXX=/path/to/clang++` if needed.
The formatter defaults to `xcrun clang-format` (Apple clang-format 16 was used
to format this repository). Linting uses the same `BOOST_PREFIX` as the build.

```sh
make -C backend test
node --version # Node 22+ is needed only for integration tests
```

The tests use temporary databases/configuration and a local mock VLM. They cover DAG ordering, invalid dependencies, JSON tool parsing, argument validation, concurrent SQLite writes, restart persistence, HTTP routes, WebSocket success/failure, cancellation, duplicate streams, desktop exclusivity, run logs, and MCP stdio. They never inject desktop input or need model credentials. Localhost networking must be allowed by the environment running the integration tests.

The CLI tests cover one-shot execution, slash commands, persistence, JSON events, invalid arguments, terminal escape filtering, and SIGINT cancellation.

Real screen capture, input injection, application launching, and model quality require a live macOS smoke test with permissions and a model configured; the automated dry-run suite does not validate those OS interactions.

## MCP stdio

```sh
./backend/build/harness --mcp
# For testing without desktop side effects:
./backend/build/harness --mcp --dry-run
```

MCP uses newline-delimited JSON-RPC on stdin/stdout, with `initialize`, `ping`, `tools/list`, and `tools/call`. Desktop tools include screenshots (with optional region or accessibility marks), application launching, click/double-click/right-click, Unicode typing, keyboard shortcuts, scrolling, dragging, cursor movement, waiting, and screen information. Diagnostics go to stderr. The transport advertises protocol version `2024-11-05`.

## Repository layout

- `backend/include/harness/core.hpp` — public C++ interfaces.
- `backend/cpp/server.cpp` — Boost.Beast HTTP/WebSocket server.
- `backend/cpp/agent.cpp` — model client, decision parsing, perception/action/evaluation loop.
- `backend/cpp/native_macos.mm` — Objective-C++ adapter for macOS frameworks.
- `backend/cpp/controller.cpp` — tool schemas, validation, allowlist, dry-run behavior.
- `backend/cpp/store.cpp` — SQLite history, compatible with existing `sessions.db` files.
- `backend/cpp/core.cpp` — configuration and DAG ordering/status helpers.
- `backend/cpp/mcp.cpp` — MCP stdio transport.
- `backend/tests/` — C++ checks and Node integration tests.
- `backend/cpp/cli.cpp` — interactive terminal client, directly linked to the agent.
- `frontend/` — optional legacy Electron/React client.

Each run writes structured events to `backend/logs/run-<id>/run.log` and, in live mode, pre/post screenshots. Existing session/subtask history remains readable. The active execution path uses one agent loop; the former experimental Python parallel-subagent scheduler and Python UI compatibility shim have been removed.
