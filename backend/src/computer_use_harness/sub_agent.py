"""
Sub-agent — the focused per-subtask perception-action loop.

Each SubAgent:
  1. Takes a screenshot via the MCP server
  2. Feeds it to the VLM to decide the next tool call
  3. Executes the tool via the MCP server
  4. Loops until the VLM calls done()/failed() or max_steps is reached
  5. Reports every step event through an async emit callback
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Awaitable

from computer_use_harness.orchestrator import Subtask
from computer_use_harness.vlm_client import VLMClient, VLMDecision

log = logging.getLogger("harness.subagent")

# Type alias for the event emitter
Emitter = Callable[[dict], Awaitable[None]]


# ── Tool executor ─────────────────────────────────────────────────────────────

def execute_decision(ctrl: Any, decision: VLMDecision, img_scale: float = 1.0) -> dict:
    """
    Dispatch a VLMDecision to the ComputerControlServer and return the result.

    img_scale is the downscale factor applied to the screenshot before it was
    sent to the VLM (e.g. 0.389 when a 1728-px-wide screen was resized to 672 px).
    Spatial coordinates output by the VLM are in downscaled image space; we
    multiply by 1/img_scale to convert them back to native screen pixels.
    """
    name = decision.tool_name
    args = decision.args

    def _native(v: int | float) -> int:
        """Convert a VLM image-space coordinate to a native screen pixel."""
        if img_scale and img_scale != 1.0:
            return round(v / img_scale)
        return int(v)

    dispatch = {
        "screenshot":  lambda: ctrl.screenshot(include_image=False),
        "open_app":    lambda: ctrl.open_app(args.get("name", "Finder")),
        "click":       lambda: ctrl.click(
                           _native(args.get("x", 400)), _native(args.get("y", 300)),
                           button=args.get("button", "left"),
                           clicks=args.get("clicks", 1),
                       ),
        "type_text":   lambda: ctrl.type_text(args.get("text", "")),
        "key_press":   lambda: ctrl.key_press(args.get("keys", ["return"])),
        "scroll":      lambda: ctrl.scroll(
                           _native(args.get("x", 640)), _native(args.get("y", 400)),
                           dx=args.get("dx", 0), dy=args.get("dy", 0),
                       ),
        "move_mouse":  lambda: ctrl.move_mouse(_native(args.get("x", 400)), _native(args.get("y", 300))),
        "wait":        lambda: ctrl.wait(args.get("ms", 1000)),
    }

    fn = dispatch.get(name)
    if fn is None:
        return {"ok": False, "error": f"unknown tool: {name!r}"}
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        log.warning(f"tool {name} raised: {exc}")
        return {"ok": False, "error": str(exc)}


def decision_to_step(decision: VLMDecision, result: dict, time_str: str) -> dict:
    """Convert a VLMDecision + its result to a step event dict."""
    ok  = result.get("ok", False)
    err = result.get("error", "unknown error")

    # Friendly label per tool
    labels = {
        "screenshot":  "Captured screen",
        "open_app":    f"Opened {decision.args.get('name', 'app').title()}" if ok else f"Failed to open {decision.args.get('name', 'app').title()}",
        "click":       f"Clicked ({decision.args.get('x')}, {decision.args.get('y')})" if ok else "Click failed",
        "type_text":   f"Typed text" if ok else "Type failed",
        "key_press":   f"Pressed {'+'.join(decision.args.get('keys', []))}" if ok else "Key press failed",
        "scroll":      "Scrolled" if ok else "Scroll failed",
        "move_mouse":  f"Moved mouse to ({decision.args.get('x')}, {decision.args.get('y')})" if ok else "Move failed",
        "wait":        f"Waited {decision.args.get('ms', 1000)}ms",
    }

    # Step type for icon colour
    type_map = {
        "screenshot": "screenshot",
        "open_app":   "keyboard",
        "click":      "mouse",
        "type_text":  "keyboard",
        "key_press":  "keyboard",
        "scroll":     "mouse",
        "move_mouse": "mouse",
        "wait":       "analyze",
    }

    # Detail string
    if not ok:
        detail = err
    elif decision.tool_name == "screenshot":
        w = result.get("width", "?")
        h = result.get("height", "?")
        detail = f"{w}×{h}"
    elif decision.tool_name == "type_text":
        text = decision.args.get("text", "")
        detail = f'type("{text[:40]}{"…" if len(text) > 40 else ""}")'
    elif decision.tool_name == "key_press":
        detail = f'key({"+".join(decision.args.get("keys", []))})'
    elif decision.tool_name in ("click", "move_mouse"):
        detail = f'click(x={decision.args.get("x")}, y={decision.args.get("y")})'
    elif decision.tool_name == "open_app":
        detail = f'open -a "{result.get("app", decision.args.get("name", ""))}"'
    else:
        detail = json.dumps(decision.args)[:80]

    return {
        "type":   type_map.get(decision.tool_name, "analyze") if ok else "error",
        "label":  labels.get(decision.tool_name, decision.tool_name),
        "detail": detail,
        "time":   time_str,
    }


# ── Sub-agent loop ────────────────────────────────────────────────────────────

class SubAgent:
    """
    Runs the perception-action loop for a single subtask.

    Events emitted (via `emit`):
      {"type": "subtask_start",    "subtask_id": str, "goal": str, "subtask_type": str}
      {"type": "subtask_step",     "subtask_id": str, "step": {...}}
      {"type": "subtask_complete", "subtask_id": str, "status": "success"|"failed"|"stuck",
                                   "notes": str}
    """

    MAX_STEPS       = 12      # max tool calls before declaring "stuck"
    SAME_ACTION_MAX = 3       # consecutive identical actions → abort
    STEP_PAUSE_S    = 0.4     # seconds between actions

    def __init__(
        self,
        subtask:    Subtask,
        ctrl:       Any,
        vlm_client: VLMClient,
        t0:         float,
        emit:       Emitter,
    ):
        self.subtask    = subtask
        self.ctrl       = ctrl
        self.vlm_client = vlm_client
        self.t0         = t0
        self.emit       = emit

    # ── Public entry point ────────────────────────────────────

    async def run(self) -> bool:
        """Execute the subtask. Returns True on success, False on failure/stuck."""
        tid  = self.subtask.id
        goal = self.subtask.goal
        stype = self.subtask.subtask_type

        log.info(f"SubAgent {tid!r}  type={stype!r}  goal={goal[:60]!r}  starting")

        await self.emit({
            "type":         "subtask_start",
            "subtask_id":   tid,
            "goal":         goal,
            "subtask_type": stype,
        })

        history: list[dict] = []
        last_actions: list[str] = []

        for step_num in range(self.MAX_STEPS):
            log.debug(f"SubAgent {tid!r}  step {step_num + 1}/{self.MAX_STEPS}")

            # 1. Screenshot
            shot = await asyncio.to_thread(
                lambda: self.ctrl.screenshot(include_image=True)
            )
            screenshot_b64 = shot.get("image_b64")
            # img_scale < 1 when the image was downscaled for the VLM;
            # coordinate outputs from the model must be divided by img_scale
            # to recover native screen-pixel positions.
            img_scale = shot.get("scale", 1.0)

            # 2. VLM decision
            decision = await self.vlm_client.decide_action(
                goal=goal,
                subtask_type=stype,
                screenshot_b64=screenshot_b64,
                history=history,
            )
            log.debug(f"SubAgent {tid!r}  decision={decision}")

            # 3. Terminal: done
            if decision.is_done:
                notes = decision.args.get("notes", "")
                step = {
                    "type":   "verify",
                    "label":  "Subtask complete",
                    "detail": notes[:120] if notes else f"Goal achieved: {goal[:60]}",
                    "time":   self._elapsed(),
                }
                await self.emit({"type": "subtask_step", "subtask_id": tid, "step": step})
                await self.emit({
                    "type":       "subtask_complete",
                    "subtask_id": tid,
                    "status":     "success",
                    "notes":      notes,
                })
                log.info(f"SubAgent {tid!r}  DONE  notes={notes[:60]!r}")
                return True

            # 4. Terminal: failed
            if decision.is_failed:
                reason = decision.args.get("reason", "")
                step = {
                    "type":   "error",
                    "label":  "Subtask failed",
                    "detail": reason[:120] if reason else f"Could not complete: {goal[:60]}",
                    "time":   self._elapsed(),
                }
                await self.emit({"type": "subtask_step", "subtask_id": tid, "step": step})
                await self.emit({
                    "type":       "subtask_complete",
                    "subtask_id": tid,
                    "status":     "failed",
                    "notes":      reason,
                })
                log.warning(f"SubAgent {tid!r}  FAILED  reason={reason[:60]!r}")
                return False

            # 5. Stuck detection — same action repeated too many times
            action_key = f"{decision.tool_name}:{json.dumps(decision.args, sort_keys=True)}"
            last_actions.append(action_key)
            if len(last_actions) >= self.SAME_ACTION_MAX:
                recent = last_actions[-self.SAME_ACTION_MAX:]
                if len(set(recent)) == 1:
                    log.warning(f"SubAgent {tid!r}  STUCK  repeated {decision.tool_name} {self.SAME_ACTION_MAX}x")
                    step = {
                        "type":   "error",
                        "label":  "Stuck — repeated action detected",
                        "detail": f"Called {decision.tool_name} {self.SAME_ACTION_MAX} times without progress",
                        "time":   self._elapsed(),
                    }
                    await self.emit({"type": "subtask_step", "subtask_id": tid, "step": step})
                    await self.emit({
                        "type":       "subtask_complete",
                        "subtask_id": tid,
                        "status":     "stuck",
                        "notes":      f"Stuck on {decision.tool_name}",
                    })
                    return False

            # 6. Execute tool (pass scale so spatial coords are remapped to native pixels)
            result = await asyncio.to_thread(lambda d=decision, s=img_scale: execute_decision(self.ctrl, d, s))
            ok = result.get("ok", False)

            # 7. Emit step
            step = decision_to_step(decision, result, self._elapsed())
            await self.emit({"type": "subtask_step", "subtask_id": tid, "step": step})

            # 8. Update VLM history — store tool call + result but NOT the screenshot bytes
            history.append({
                "role":       "assistant",
                "content":    None,
                "tool_calls": [{
                    "id":       f"call_{step_num}",
                    "type":     "function",
                    "function": {
                        "name":      decision.tool_name,
                        "arguments": json.dumps(decision.args),
                    },
                }],
            })
            # Store result as text — strip large binary fields (e.g. image_b64) so the
            # history doesn't balloon with base64 image data across steps.
            safe_result = {k: v for k, v in result.items() if k != "image_b64"}
            history.append({
                "role":         "tool",
                "tool_call_id": f"call_{step_num}",
                "content":      json.dumps(safe_result),
            })

            if not ok:
                log.debug(f"SubAgent {tid!r}  tool {decision.tool_name} failed: {result.get('error')}")

            await asyncio.sleep(self.STEP_PAUSE_S)

        # Max steps exceeded
        log.warning(f"SubAgent {tid!r}  max steps ({self.MAX_STEPS}) exceeded → stuck")
        step = {
            "type":   "error",
            "label":  f"Max steps ({self.MAX_STEPS}) reached",
            "detail": "Sub-agent did not resolve within the step limit",
            "time":   self._elapsed(),
        }
        await self.emit({"type": "subtask_step", "subtask_id": tid, "step": step})
        await self.emit({
            "type":       "subtask_complete",
            "subtask_id": tid,
            "status":     "stuck",
            "notes":      f"Exceeded {self.MAX_STEPS} steps",
        })
        return False

    # ── Helpers ───────────────────────────────────────────────

    def _elapsed(self) -> str:
        return f"{time.time() - self.t0:.1f}s"


__all__ = ["SubAgent", "execute_decision", "decision_to_step"]
