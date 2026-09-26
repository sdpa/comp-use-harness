"""
Computer-Use Harness — FastAPI + WebSocket backend server.
Run with: python server.py  (starts on http://127.0.0.1:7123)

WebSocket event stream (server → client):
  {"type": "info",               "message": str, "dry_run": bool}
  {"type": "plan",               "subtasks": [{id, goal, subtask_type, depends_on, status}]}
  {"type": "subtask_start",      "subtask_id": str, "goal": str, "subtask_type": str}
  {"type": "subtask_step",       "subtask_id": str, "step": {type, label, detail, time}}
  {"type": "subtask_complete",   "subtask_id": str, "status": str, "notes": str}
  {"type": "subtask_replanning", "subtask_id": str, "attempt": int, "new_goal": str}
  {"type": "step",               "step": {...}}   (top-level steps, e.g. initial screenshot)
  {"type": "task_failed",        "subtask_id": str, "detail": str}
  {"type": "complete",           "status": str, "elapsed_ms": int}
  {"type": "error",              "message": str}
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

# ── Logging ───────────────────────────────────────────────────────────────────
# ── Colored console formatter ─────────────────────────────────────────────────
# ANSI colours used per logger name prefix:
#   harness.vlm  →  magenta (PERCEIVE) / cyan (DECIDE) / yellow (parse)
#   harness.mcp  →  green
#   harness.*    →  default terminal colour
_ANSI = {
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "grey":    "\033[90m",
    "green":   "\033[32m",
    "yellow":  "\033[33m",
    "blue":    "\033[34m",
    "magenta": "\033[35m",
    "cyan":    "\033[36m",
    "red":     "\033[31m",
    "bright_red": "\033[91m",
}

class _ColorFormatter(logging.Formatter):
    """
    Colour-code log lines by logger name and message content so that
    LLM API calls stand out at a glance in the terminal.

    Colour legend
    ─────────────
    magenta  VLM PERCEIVE cell call  (harness.vlm + "VLM CELL" or "perceive")
    cyan     VLM DECIDE call         (harness.vlm + "VLM →" or "_sync_call")
    yellow   VLM parse / result      (harness.vlm, other)
    green    MCP tool call           (harness.mcp)
    grey     DEBUG lines             (any logger)
    red      WARNING / ERROR         (any logger)
    """

    _BASE_FMT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
    _DATE_FMT = "%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        msg    = super().format(record)
        name   = record.name
        level  = record.levelno
        text   = record.getMessage()
        R      = _ANSI["reset"]

        if level >= logging.ERROR:
            colour = _ANSI["bright_red"]
        elif level >= logging.WARNING:
            colour = _ANSI["red"]
        elif level == logging.DEBUG:
            colour = _ANSI["grey"]
        elif name.startswith("harness.vlm"):
            # Distinguish perceive vs decide vs parse within VLM logger
            tl = text.lower()
            if "cell" in tl or "perceive" in tl:
                colour = _ANSI["magenta"]
            elif "vlm →" in tl or "_sync_call" in tl or "decide" in tl or "vlm messages" in tl:
                colour = _ANSI["cyan"]
            else:
                colour = _ANSI["yellow"]
        elif name.startswith("harness.mcp"):
            colour = _ANSI["green"]
        else:
            colour = ""   # default terminal colour

        return f"{colour}{msg}{R}" if colour else msg

    def __init__(self):
        super().__init__(fmt=self._BASE_FMT, datefmt=self._DATE_FMT)


_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_ColorFormatter())

logging.root.setLevel(logging.DEBUG)
logging.root.handlers = []          # clear any handlers basicConfig might have added
logging.root.addHandler(_console_handler)

log = logging.getLogger("harness")

# ── Logs directory ────────────────────────────────────────────────────────────
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

_LOG_FMT = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

# ── Path setup ────────────────────────────────────────────────────────────────
_VENV = Path(__file__).parent / ".venv" / "lib" / "python3.13" / "site-packages"
if _VENV.exists():
    sys.path.insert(0, str(_VENV))

sys.path.insert(0, str(Path(__file__).parent / "src"))

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from computer_use_harness.agent_loop    import AgentLoop
from computer_use_harness.mcp_server    import build_server
from computer_use_harness.vlm_client    import VLMClient
from computer_use_harness.session_store import SessionStore

# ── Config store (VLM settings) ───────────────────────────────────────────────
import json
import os

_CONFIG_PATH = Path(__file__).parent / "vlm_config.json"

def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}

def _save_config(cfg: dict) -> None:
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Computer-Use Harness API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Shared resources ──────────────────────────────────────────────────────────
_store: SessionStore | None = None

@app.on_event("startup")
async def _startup() -> None:
    global _store
    _store = SessionStore()
    await _store.init()
    log.info("SessionStore initialised")


def _get_vlm() -> VLMClient:
    cfg = _load_config()
    return VLMClient(
        base_url=cfg.get("vlm_base_url"),
        model=cfg.get("vlm_model"),
        api_key=cfg.get("vlm_api_key"),
    )

# ── In-memory task store (active/recent tasks) ────────────────────────────────
_tasks: dict[str, dict] = {}

# ── Root + CDP probe endpoints ────────────────────────────────────────────────

@app.get("/")
def root():
    """Root endpoint — prevents 404 noise from browser/DevTools probes."""
    return {"name": "Computer-Use Harness", "version": "0.2.0", "api": "/api/health"}

@app.get("/json/version")
def cdp_version():
    """Chrome DevTools Protocol probe endpoint — return empty to silence 404s."""
    return {}

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    log.debug("GET /api/health")
    return {"status": "ok", "version": "0.2.0"}

# ── Config ───────────────────────────────────────────────────────────────────

@app.get("/api/config")
def get_config():
    cfg = _load_config()
    return {
        "vlm_base_url": cfg.get("vlm_base_url", ""),
        "vlm_model":    cfg.get("vlm_model", "qwen2.5-vl:7b"),
        "vlm_enabled":  bool(cfg.get("vlm_base_url")),
    }

@app.post("/api/config")
async def save_config(body: dict):
    cfg = _load_config()
    if "vlm_base_url" in body:
        cfg["vlm_base_url"] = body["vlm_base_url"]
    if "vlm_model" in body:
        cfg["vlm_model"] = body["vlm_model"]
    if "vlm_api_key" in body:
        cfg["vlm_api_key"] = body["vlm_api_key"]
    _save_config(cfg)
    log.info(f"Config saved: vlm_base_url={cfg.get('vlm_base_url')!r}  model={cfg.get('vlm_model')!r}")
    return {"saved": True}

# ── Session history ───────────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions():
    if _store is None:
        return []
    return await _store.list_sessions()

@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    if _store is None:
        return {"error": "Store not ready"}
    data = await _store.get_session(session_id)
    if data is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")
    return data

# ── In-memory tasks (legacy / active tasks) ───────────────────────────────────

@app.get("/api/tasks")
def list_tasks():
    log.info(f"GET /api/tasks → {len(_tasks)} tasks")
    return [
        {
            "id":         t["id"],
            "prompt":     t["prompt"],
            "status":     t["status"],
            "created_at": t["created_at"],
            "elapsed_ms": t.get("elapsed_ms", 0),
        }
        for t in reversed(list(_tasks.values()))
    ]

@app.post("/api/tasks")
async def create_task(body: dict):
    task_id = str(uuid.uuid4())
    run_id  = f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{task_id[:8]}"
    prompt  = body.get("prompt", "")
    log.info(f"POST /api/tasks  id={task_id}  run_id={run_id}  prompt={prompt!r:.80}")
    _tasks[task_id] = {
        "id":         task_id,
        "run_id":     run_id,
        "prompt":     prompt,
        "status":     "pending",
        "steps":      [],
        "created_at": time.time(),
        "elapsed_ms": 0,
    }
    return _tasks[task_id]

# ── WebSocket streaming ───────────────────────────────────────────────────────

@app.websocket("/api/tasks/{task_id}/stream")
async def stream_task(websocket: WebSocket, task_id: str):
    await websocket.accept()
    log.info(f"WS open  task_id={task_id}")

    task = _tasks.get(task_id)
    if not task:
        log.warning(f"WS task not found: {task_id}")
        await websocket.send_json({"type": "error", "message": "Task not found"})
        await websocket.close()
        return

    # ── Per-run directory + file logging ─────────────────────────────────────
    run_id   = task["run_id"]
    run_dir  = LOGS_DIR / run_id          # e.g. logs/run-20260908-075718-8159f1d2/
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"
    _fh      = logging.FileHandler(log_path, encoding="utf-8")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(_LOG_FMT)
    logging.getLogger("harness").addHandler(_fh)
    log.info(f"run_id={run_id}  log_file={log_path}")

    task["status"] = "running"
    t0             = time.time()
    log.info(f"WS running  prompt={task['prompt']!r:.80}")

    step_count  = 0
    task_ok     = True
    fail_detail = ""

    try:
        async for event in _run_computer_use(task["prompt"], t0, task_id, run_id, run_dir):
            if event.get("type") == "step":
                step = event["step"]
                step_count += 1
                task["steps"].append(step)
                log.info(
                    f"WS step #{step_count:02d} [{step['type']:12s}] {step['label']}  t={step.get('time', '')}"
                )
            elif event.get("type") == "task_failed":
                task_ok     = False
                fail_detail = event.get("detail", "A step failed")
            await websocket.send_json(event)

        elapsed_ms          = int((time.time() - t0) * 1000)
        task["elapsed_ms"]  = elapsed_ms

        if task_ok:
            task["status"] = "success"
            log.info(f"WS complete  steps={step_count}  elapsed={elapsed_ms}ms")
            await websocket.send_json(
                {"type": "complete", "status": "success", "elapsed_ms": elapsed_ms}
            )
        else:
            task["status"] = "error"
            log.warning(f"WS failed  elapsed={elapsed_ms}ms  detail={fail_detail!r}")
            await websocket.send_json(
                {"type": "error", "message": fail_detail or "Task failed", "elapsed_ms": elapsed_ms}
            )

    except WebSocketDisconnect:
        log.info(f"WS client disconnected  task_id={task_id}")
        task["status"] = "cancelled"
    except Exception as exc:  # noqa: BLE001
        log.exception(f"WS error during task {task_id}: {exc}")
        task["status"] = "error"
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:  # noqa: BLE001
            pass
    finally:
        log.info(f"WS closed  task_id={task_id}  run_id={run_id}  status={task['status']}  dir={run_dir}")
        # Remove per-run file handler
        logging.getLogger("harness").removeHandler(_fh)
        _fh.close()
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


# ── Core orchestration runner ─────────────────────────────────────────────────

async def _run_computer_use(
    prompt:     str,
    t0:         float,
    session_id: str,
    run_id:     str,
    run_dir:    Path,
) -> AsyncGenerator[dict, None]:
    """
    Orchestrate a task end-to-end and yield WebSocket events.
    Uses the real VLM + MCP server + single agent loop.
    """
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    # Run orchestration in a background task so we can yield from the queue
    bg_task = asyncio.create_task(_orchestrate(prompt, t0, session_id, run_id, run_dir, queue))

    try:
        while True:
            event = await queue.get()
            if event is None:  # sentinel — orchestration finished
                break
            yield event
    finally:
        if not bg_task.done():
            bg_task.cancel()
            try:
                await bg_task
            except (asyncio.CancelledError, Exception):
                pass


async def _orchestrate(
    prompt:     str,
    t0:         float,
    session_id: str,
    run_id:     str,
    run_dir:    Path,
    queue:      asyncio.Queue,
) -> None:
    """Full orchestration logic — puts events into queue."""

    def elapsed() -> str:
        return f"{time.time() - t0:.1f}s"

    async def emit(event: dict) -> None:
        await queue.put(event)

    try:
        ctrl = build_server(dry_run=False)
        vlm  = _get_vlm()

        log.info(f"orchestrate  run_id={run_id}  vlm_enabled={vlm.enabled}  prompt={prompt!r:.80}")

        # ── Initial screenshot ────────────────────────────────────────────────
        shot_result = await asyncio.to_thread(
            lambda: ctrl.screenshot(include_image=False)
        )
        if shot_result.get("ok"):
            w = shot_result.get("width", "?")
            h = shot_result.get("height", "?")
            await emit(_step("screenshot", "Captured screen", f"{w}×{h}", elapsed()))
        else:
            await emit(_step("analyze", "Screen capture skipped", shot_result.get("error", ""), elapsed()))

        await emit({
            "type":        "info",
            "dry_run":     False,
            "vlm_enabled": vlm.enabled,
            "run_id":      run_id,
            "message": (
                f"VLM enabled ({vlm.model})" if vlm.enabled
                else "Heuristic mode (set COMPUTER_USE_VLM_BASE_URL for real VLM)"
            ),
        })

        # ── Session store: create session ─────────────────────────────────────
        if _store:
            await _store.create_session(session_id, prompt)

        # ── Single agent loop ─────────────────────────────────────────────────
        log.info(f"agent_loop  run_id={run_id}  starting")
        all_success = await AgentLoop().run(
            instruction=prompt,
            ctrl=ctrl,
            vlm=vlm,
            t0=t0,
            emit=emit,
            store=_store,
            session_id=session_id,
            run_dir=run_dir,
        )

        # ── Final step ────────────────────────────────────────────────────────
        elapsed_ms = int((time.time() - t0) * 1000)

        if all_success:
            await emit(_step("complete", "Task complete", prompt.strip(), elapsed()))

        if _store:
            await _store.complete_session(
                session_id,
                status="success" if all_success else "error",
                elapsed_ms=elapsed_ms,
            )

    except Exception as exc:  # noqa: BLE001
        log.exception(f"orchestrate error: {exc}")
        await emit({"type": "error", "message": str(exc)})
        if _store:
            try:
                await _store.complete_session(session_id, "error", int((time.time() - t0) * 1000))
            except Exception:  # noqa: BLE001
                pass
    finally:
        await queue.put(None)  # sentinel


# ── Helpers ───────────────────────────────────────────────────────────────────

def _step(kind: str, label: str, detail: str, time_str: str) -> dict:
    return {"type": "step", "step": {"type": kind, "label": label, "detail": detail, "time": time_str}}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port   = 7123
    ws_lib = None
    for lib in ("wsproto", "websockets"):
        try:
            __import__(lib)
            ws_lib = lib
            break
        except ImportError:
            pass

    if ws_lib is None:
        print(
            "[harness] ERROR: no WebSocket library found.\n"
            "  Run:  pip install wsproto",
            flush=True,
        )
        raise SystemExit(1)

    log.info(f"backend starting on http://127.0.0.1:{port}  ws={ws_lib}")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        ws="wsproto",
    )
