"""
Agent loop — single continuous perception-thought-action-evaluate loop.

Based on the UI-TARS architecture (Qin et al., 2025):
  Each step:  screenshot  →  thought  →  action  →  evaluate  →  (reflect | continue)

The loop owns the full task context: original instruction, full
(thought, action, evaluation) history, step counter, reflection state.
Task decomposition, milestone tracking and error recovery all happen
as *reasoning within this one loop*, not as separate spawned processes.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Awaitable

from computer_use_harness.accessibility import get_ui_elements_text

log = logging.getLogger("harness.agent")

# Type alias
Emitter = Callable[[dict], Awaitable[None]]

# ── Tunables ──────────────────────────────────────────────────────────────────
MAX_STEPS      = 30   # hard step cap before declaring stuck
REFLECTION_CAP = 3    # consecutive failed-eval steps before giving up
HISTORY_WINDOW = 8    # how many past steps to include in VLM context
STEP_PAUSE_S   = 0.35 # seconds to wait after an action (OS settle time)
EVAL_DIFF_THRESHOLD = 4.0  # mean pixel diff (0–255 on 32×32 greyscale) to count as "changed"


# ── AgentLoop ─────────────────────────────────────────────────────────────────

class AgentLoop:
    """
    Runs the single perception-thought-action-evaluate loop until the VLM
    calls `finished`, hits `REFLECTION_CAP` consecutive stalls, or exhausts
    `MAX_STEPS`.

    Emits these WebSocket event dicts via `emit`:
      {"type": "step",        "step": {type, label, detail, time, is_reflection?}}
      {"type": "task_failed", "subtask_id": "", "detail": str}
      {"type": "call_user",   "question": str}
    """

    async def run(
        self,
        instruction: str,
        ctrl:        Any,
        vlm:         Any,
        t0:          float,
        emit:        Emitter,
        store:       Any | None = None,
        session_id:  str | None = None,
        run_dir:     Path | None = None,
    ) -> bool:
        """Execute the loop. Returns True on success, False on failure."""
        history:                 list[dict] = []
        consecutive_reflections: int        = 0

        def elapsed() -> str:
            return f"{time.time() - t0:.1f}s"

        def save_shot(shot: dict, name: str) -> None:
            """Write a screenshot's PNG bytes to run_dir/<name>.png (best-effort)."""
            if run_dir is None:
                return
            b64 = shot.get("image_b64")
            if not b64:
                return
            try:
                path = run_dir / f"{name}.png"
                path.write_bytes(base64.b64decode(b64))
                log.debug(f"screenshot saved → {path.name}")
            except Exception as exc:  # noqa: BLE001
                log.debug(f"save_shot failed ({exc})")

        async def log_step(step: dict) -> None:
            await emit({"type": "step", "step": step})
            if store and session_id:
                await store.log_step(session_id, None, step)

        for step_num in range(MAX_STEPS):
            log.debug(
                f"AgentLoop  step={step_num + 1}/{MAX_STEPS}  "
                f"reflections={consecutive_reflections}"
            )

            # ── 1. Screenshot + UI element detection (observation) ────────────
            pre_shot = await asyncio.to_thread(
                lambda: ctrl.screenshot(include_image=True)
            )
            img_scale      = pre_shot.get("scale", 1.0)
            screenshot_b64 = pre_shot.get("image_b64")
            save_shot(pre_shot, f"step-{step_num + 1:03d}-pre")

            # Query macOS Accessibility API for interactive element positions.
            # Hard 2 s timeout — atomacos can block indefinitely if the permission
            # dialog is pending or if the frontmost app is unresponsive.
            try:
                ui_elements = await asyncio.wait_for(
                    asyncio.to_thread(lambda s=img_scale: get_ui_elements_text(scale=s)),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                log.warning("AgentLoop  ax_elements: timed out (>2 s) — skipping")
                ui_elements = ""
            except Exception as _ax_exc:  # noqa: BLE001
                log.debug(f"AgentLoop  ax_elements: error ({_ax_exc}) — skipping")
                ui_elements = ""

            if ui_elements:
                log.debug(f"AgentLoop  ax_elements={len(ui_elements.splitlines())}  preview={ui_elements[:120]!r}")
            else:
                log.debug("AgentLoop  ax_elements=none")

            # ── 2a. Phase 1 — Explore: perceive the screenshot as a 4×4 grid ──
            # The model describes what is on screen before deciding what to do.
            # This prevents it from blindly following system-prompt examples and
            # forces explicit grounding ("no browser visible → open Safari first").
            perception = await vlm.perceive_screenshot(screenshot_b64)
            if perception:
                log.debug(f"AgentLoop  perception ({len(perception.splitlines())} lines):\n{perception}")
                # Emit a lightweight thought step so the UI shows what the model sees
                await log_step({
                    "type":   "analyze",
                    "label":  "Perceiving screen",
                    "detail": perception[:300],
                    "time":   elapsed(),
                })
            else:
                log.debug("AgentLoop  perception=none (VLM disabled or failed)")

            # ── 2b. Phase 2 — Exploit: decide action based on perception ──────
            is_reflection = consecutive_reflections > 0
            decision = await vlm.decide_action(
                instruction=instruction,
                history=history[-HISTORY_WINDOW:],
                screenshot_b64=screenshot_b64,
                ui_elements=ui_elements or None,
                perception=perception or None,
                is_reflection=is_reflection,
            )
            log.debug(f"AgentLoop  decision={decision!r}")

            # ── 3. Emit thought ───────────────────────────────────────────────
            if decision.thought:
                await log_step({
                    "type":          "thought",
                    "label":         "Reflection" if is_reflection else "Reasoning",
                    "detail":        decision.thought[:400],
                    "time":          elapsed(),
                    "is_reflection": is_reflection,
                })

            # ── 4. Terminal: finished ─────────────────────────────────────────
            if decision.tool_name == "finished":
                summary = decision.args.get("summary", "")
                await log_step({
                    "type":   "verify",
                    "label":  "Task complete",
                    "detail": summary or instruction.strip(),
                    "time":   elapsed(),
                })
                log.info(f"AgentLoop  FINISHED  summary={summary[:80]!r}")
                return True

            # ── 5. Terminal: call_user ────────────────────────────────────────
            if decision.tool_name == "call_user":
                question = decision.args.get("question", "")
                await emit({"type": "call_user", "question": question})
                log.info(f"AgentLoop  CALL_USER  question={question[:80]!r}")
                return False

            # ── 6. Terminal: failed ───────────────────────────────────────────
            if decision.tool_name == "failed":
                reason = decision.args.get("reason", "")
                await emit({"type": "task_failed", "subtask_id": "", "detail": reason})
                log.warning(f"AgentLoop  FAILED  reason={reason[:80]!r}")
                return False

            # ── 7. Execute action ─────────────────────────────────────────────
            result = await asyncio.to_thread(
                lambda d=decision, s=img_scale: _execute(ctrl, d, s)
            )

            # ── 8. Emit action step ───────────────────────────────────────────
            await log_step(_action_to_step(decision, result, elapsed(), is_reflection))

            # ── 9. Pause for OS to settle ─────────────────────────────────────
            await asyncio.sleep(STEP_PAUSE_S)

            # ── 10. Post-action screenshot → evaluate ─────────────────────────
            post_shot = await asyncio.to_thread(
                lambda: ctrl.screenshot(include_image=True)
            )
            save_shot(post_shot, f"step-{step_num + 1:03d}-post")
            eval_ok = _evaluate(pre_shot, post_shot, decision, result)
            log.debug(f"AgentLoop  eval_ok={eval_ok}  tool={decision.tool_name}")

            # ── 11. Update compact history ────────────────────────────────────
            history.append({
                "step":      step_num + 1,
                "thought":   decision.thought or "",
                "action":    decision.tool_name,
                "args":      decision.args,
                "result_ok": result.get("ok", False),
                "eval_ok":   eval_ok,
            })

            # ── 11b. Stuck detection: same action+args repeated ≥3 times ─────
            # Even if each individual eval passed, repeating the exact same
            # action with identical args means nothing is actually changing.
            if len(history) >= 3:
                last3 = history[-3:]
                same = all(
                    h["action"] == decision.tool_name and h["args"] == decision.args
                    for h in last3
                )
                if same and decision.tool_name not in ("open_app",):
                    log.warning(
                        f"AgentLoop  REPEATED_ACTION: '{decision.tool_name}' "
                        f"with {decision.args} x3 — forcing reflection"
                    )
                    eval_ok = False  # override: treat as stuck

            # ── 12. Reflect or continue ───────────────────────────────────────
            if not eval_ok:
                consecutive_reflections += 1
                if consecutive_reflections >= REFLECTION_CAP:
                    detail = (
                        f"Action '{decision.tool_name}' had no visible effect "
                        f"{REFLECTION_CAP} times in a row — giving up"
                    )
                    await emit({"type": "task_failed", "subtask_id": "", "detail": detail})
                    log.warning(f"AgentLoop  STUCK  reflections={consecutive_reflections}")
                    return False

                await log_step({
                    "type":          "analyze",
                    "label":         f"Reflection {consecutive_reflections}/{REFLECTION_CAP}",
                    "detail":        (
                        f"'{decision.tool_name}' had no visible effect — "
                        "retrying with reflection"
                    ),
                    "time":          elapsed(),
                    "is_reflection": True,
                })
            else:
                consecutive_reflections = 0

        # Max steps exceeded
        detail = f"Exceeded {MAX_STEPS} steps without completing the task"
        await emit({"type": "task_failed", "subtask_id": "", "detail": detail})
        log.warning(f"AgentLoop  MAX_STEPS exceeded")
        return False


# ── Tool execution ─────────────────────────────────────────────────────────────

def _execute(ctrl: Any, decision: Any, img_scale: float = 1.0) -> dict:
    """
    Dispatch a VLMDecision to the ComputerControlServer.

    img_scale < 1 means the screenshot was downscaled before being sent to
    the VLM.  Coordinate outputs from the model are in the *downscaled* image
    space; multiplying by 1/img_scale converts them to native screen pixels.
    """
    name = decision.tool_name
    args = decision.args

    def _native(v: int | float) -> int:
        return round(v / img_scale) if img_scale and img_scale != 1.0 else int(v)

    dispatch: dict = {
        "screenshot":   lambda: ctrl.screenshot(include_image=False),
        "open_app":     lambda: ctrl.open_app(args.get("name", "Finder")),
        "click":        lambda: ctrl.click(
                            _native(args.get("x", 400)), _native(args.get("y", 300)),
                            button=args.get("button", "left"),
                            clicks=args.get("clicks", 1),
                        ),
        "left_double":  lambda: ctrl.click(
                            _native(args.get("x", 400)), _native(args.get("y", 300)),
                            button="left", clicks=2,
                        ),
        "right_single": lambda: ctrl.click(
                            _native(args.get("x", 400)), _native(args.get("y", 300)),
                            button="right", clicks=1,
                        ),
        "drag":         lambda: ctrl.drag(
                            _native(args.get("x1", 300)), _native(args.get("y1", 300)),
                            _native(args.get("x2", 500)), _native(args.get("y2", 300)),
                        ),
        "type_text":    lambda: ctrl.type_text(args.get("text", "")),
        "key_press":    lambda: ctrl.key_press(args.get("keys", ["return"])),
        "hotkey":       lambda: ctrl.key_press(args.get("keys", [])),
        "scroll":       lambda: ctrl.scroll(
                            _native(args.get("x", 640)), _native(args.get("y", 400)),
                            dx=args.get("dx", 0), dy=args.get("dy", 0),
                        ),
        "move_mouse":   lambda: ctrl.move_mouse(
                            _native(args.get("x", 400)), _native(args.get("y", 300))
                        ),
        "wait":         lambda: ctrl.wait(args.get("ms", 1000)),
    }

    fn = dispatch.get(name)
    if fn is None:
        return {"ok": False, "error": f"unknown tool: {name!r}"}
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        log.warning(f"tool {name} raised: {exc}")
        return {"ok": False, "error": str(exc)}


# ── Evaluate ───────────────────────────────────────────────────────────────────

def _evaluate(
    pre_shot:  dict,
    post_shot: dict,
    decision:  Any,
    result:    dict,
) -> bool:
    """
    Objective check: did the action have the expected effect?

    Returns True (action worked / continue), False (no change / reflect).
    """
    # Tool-level: if the tool itself failed, action failed
    if not result.get("ok", False):
        return False

    # Non-visual tools — trust the tool result, not pixels
    # key_press / type_text / hotkey: effects are often invisible at thumbnail
    # scale (focus rings, cursor blink, caret position).  Trust ok=True.
    non_visual = {
        "screenshot", "wait", "move_mouse", "get_screen_info",
        "key_press", "hotkey", "type_text",
    }
    if decision.tool_name in non_visual:
        return True

    # open_app: trust the tool's own success signal
    if decision.tool_name == "open_app":
        return result.get("ok", False)

    # Visual diff: compare pre- and post-action screenshots
    pre_b64  = pre_shot.get("image_b64", "")
    post_b64 = post_shot.get("image_b64", "")

    if not pre_b64 or not post_b64:
        return True  # can't diff → trust tool result

    if pre_b64 == post_b64:
        # Identical base64 → byte-for-byte same frame
        log.debug("evaluate  identical frames → no change")
        return False

    try:
        from PIL import Image  # type: ignore
        from io import BytesIO

        pre_img  = Image.open(BytesIO(base64.b64decode(pre_b64))).convert("L").resize((32, 32))
        post_img = Image.open(BytesIO(base64.b64decode(post_b64))).convert("L").resize((32, 32))

        pre_data  = list(pre_img.getdata())
        post_data = list(post_img.getdata())
        diff = sum(abs(a - b) for a, b in zip(pre_data, post_data)) / len(pre_data)

        changed = diff >= EVAL_DIFF_THRESHOLD
        log.debug(f"evaluate  pixel_diff={diff:.2f}  threshold={EVAL_DIFF_THRESHOLD}  changed={changed}")
        return changed

    except Exception as exc:  # noqa: BLE001
        log.debug(f"evaluate  diff failed ({exc}) — trusting tool result")
        return True  # fallback: trust the tool


# ── Step formatting ────────────────────────────────────────────────────────────

def _action_to_step(
    decision:     Any,
    result:       dict,
    time_str:     str,
    is_reflection: bool = False,
) -> dict:
    """Convert a VLMDecision + its result into a step event dict."""
    ok   = result.get("ok", False)
    name = decision.tool_name
    args = decision.args

    _TYPE_MAP = {
        "screenshot":   "screenshot",
        "open_app":     "keyboard",
        "click":        "mouse",
        "left_double":  "mouse",
        "right_single": "mouse",
        "drag":         "mouse",
        "type_text":    "keyboard",
        "key_press":    "keyboard",
        "hotkey":       "keyboard",
        "scroll":       "mouse",
        "move_mouse":   "mouse",
        "wait":         "analyze",
    }

    if name == "screenshot":
        label  = "Captured screen"
        detail = f"{result.get('width', '?')}×{result.get('height', '?')}"
    elif name == "open_app":
        app    = result.get("app", args.get("name", "app"))
        label  = f"Opened {app}" if ok else f"Failed to open {args.get('name', 'app')}"
        detail = f'open -a "{app}"'
    elif name in ("click", "left_double", "right_single"):
        x, y   = args.get("x"), args.get("y")
        prefix = "Double-" if name == "left_double" else ("Right-" if name == "right_single" else "")
        label  = f"{prefix}Clicked ({x}, {y})" if ok else "Click failed"
        detail = f'{"double_" if name == "left_double" else "right_" if name == "right_single" else ""}click(x={x}, y={y})'
    elif name == "drag":
        label  = f"Dragged ({args.get('x1')},{args.get('y1')}) → ({args.get('x2')},{args.get('y2')})" if ok else "Drag failed"
        detail = f"drag({args.get('x1')},{args.get('y1')} → {args.get('x2')},{args.get('y2')})"
    elif name == "type_text":
        text   = args.get("text", "")
        label  = "Typed text" if ok else "Type failed"
        detail = f'type("{text[:40]}{"…" if len(text) > 40 else ""}")'
    elif name in ("key_press", "hotkey"):
        keys   = args.get("keys", [])
        label  = f"Pressed {'+'.join(keys)}" if ok else "Key press failed"
        detail = f'hotkey({"+".join(keys)})'
    elif name == "scroll":
        label  = "Scrolled" if ok else "Scroll failed"
        detail = f'scroll(x={args.get("x")}, y={args.get("y")}, dy={args.get("dy", 0)})'
    elif name == "move_mouse":
        label  = f"Moved mouse to ({args.get('x')}, {args.get('y')})"
        detail = f'move({args.get("x")}, {args.get("y")})'
    elif name == "wait":
        label  = f"Waited {args.get('ms', 1000)} ms"
        detail = f'wait({args.get("ms", 1000)} ms)'
    else:
        label  = name
        detail = json.dumps(args)[:80]

    if not ok:
        err_msg = result.get("error", "")
        if err_msg:
            label = err_msg[:80]

    step = {
        "type":   _TYPE_MAP.get(name, "analyze") if ok else "error",
        "label":  label,
        "detail": detail,
        "time":   time_str,
    }
    if is_reflection:
        step["is_reflection"] = True
    return step


__all__ = ["AgentLoop"]
