"""
VLM client — OpenAI-compatible vision + tool-calling API for sub-agents.

Configure via environment variables:
  COMPUTER_USE_VLM_BASE_URL  e.g. http://localhost:11434/v1   (Ollama)
  COMPUTER_USE_VLM_MODEL     e.g. qwen2.5-vl:7b
  COMPUTER_USE_VLM_API_KEY   optional; defaults to "ollama"

Without COMPUTER_USE_VLM_BASE_URL the client runs in heuristic-fallback mode
so the harness remains functional without a VLM server.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

log = logging.getLogger("harness.vlm")

# ── Unified tool set exposed to the VLM (UI-TARS action space) ───────────────
#
# The single agent loop has access to the full action space — no per-subtask
# restriction needed.  Terminal tools (`finished`, `call_user`, `failed`) end
# the loop; all others are forwarded to the MCP server.

COMPUTER_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "Capture the current screen state. Use to re-observe after an action or when uncertain about UI state.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Launch a macOS application by name (e.g. 'Safari', 'Calculator', 'Music'). No Accessibility permission needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Application name as shown in /Applications"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Single left-click at pixel coordinates. Use precise coordinates from the screenshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X pixel coordinate (in the screenshot's coordinate space)"},
                    "y": {"type": "integer", "description": "Y pixel coordinate (in the screenshot's coordinate space)"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "left_double",
            "description": "Double left-click at pixel coordinates (e.g. to open a file or activate an item).",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "right_single",
            "description": "Single right-click at pixel coordinates to open a context menu.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drag",
            "description": "Click-and-drag from (x1, y1) to (x2, y2), e.g. to move a window or select text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x1": {"type": "integer", "description": "Drag start X"},
                    "y1": {"type": "integer", "description": "Drag start Y"},
                    "x2": {"type": "integer", "description": "Drag end X"},
                    "y2": {"type": "integer", "description": "Drag end Y"},
                },
                "required": ["x1", "y1", "x2", "y2"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type a string of text into the currently focused element.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to type"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "key_press",
            "description": "Press keyboard keys or shortcuts. E.g. ['cmd', 'space'] for Spotlight, ['return'] for Enter, ['escape'] to dismiss.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}, "description": "Key names or modifier+key combos"}
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll at a position. dy > 0 scrolls down, dy < 0 scrolls up.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x":  {"type": "integer"},
                    "y":  {"type": "integer"},
                    "dx": {"type": "integer", "default": 0, "description": "Horizontal scroll amount"},
                    "dy": {"type": "integer", "default": 0, "description": "Vertical scroll amount (positive=down)"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_mouse",
            "description": "Move the mouse cursor without clicking, e.g. to trigger hover states.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Wait for a number of milliseconds (e.g. for an animation or app launch to settle).",
            "parameters": {
                "type": "object",
                "properties": {"ms": {"type": "integer", "default": 1000, "description": "Milliseconds to wait"}},
                "required": [],
            },
        },
    },
    # ── Terminal tools ────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "finished",
            "description": (
                "Report that the FULL task has been successfully completed. "
                "Only call this when you can visually confirm the final goal state is reached."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Brief description of what was accomplished and what is visible now"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_user",
            "description": "Pause the task and ask the user a question when you genuinely cannot proceed without human input.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask the user"}
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "failed",
            "description": "Report that the task CANNOT be completed. Only call after genuine attempts have all failed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Clear explanation of why the task failed and what was attempted"}
                },
                "required": [],
            },
        },
    },
]


# ── Decision dataclass ────────────────────────────────────────────────────────

class VLMDecision:
    """
    A single decision from the VLM: chain-of-thought + one tool call.

    `thought` carries the model's reasoning (extracted from <think>…</think>
    blocks or a reasoning prefix).  It is shown in the UI step feed but is
    never sent back as history images — only compact text summaries are kept.
    """

    def __init__(self, tool_name: str, args: dict[str, Any], thought: str = ""):
        self.tool_name = tool_name
        self.args      = dict(args)
        self.thought   = thought.strip()

    @property
    def is_terminal(self) -> bool:
        return self.tool_name in ("finished", "call_user", "failed")

    def __repr__(self) -> str:
        thought_preview = f"  thought={self.thought[:60]!r}" if self.thought else ""
        return f"VLMDecision({self.tool_name}, {self.args}{thought_preview})"


# ── VLMClient ─────────────────────────────────────────────────────────────────

class VLMClient:
    """
    Wraps an OpenAI-compatible inference API.
    Falls back to keyword-heuristic decisions when no VLM is configured.
    """

    def __init__(
        self,
        base_url:  str | None = None,
        model:     str | None = None,
        api_key:   str | None = None,
    ):
        self.base_url = (base_url or os.environ.get("COMPUTER_USE_VLM_BASE_URL", "")).rstrip("/")
        self.model    = model   or os.environ.get("COMPUTER_USE_VLM_MODEL",    "qwen2.5-vl:7b")
        self.api_key  = api_key or os.environ.get("COMPUTER_USE_VLM_API_KEY",  "ollama")
        self.enabled  = bool(self.base_url)
        log.info(f"VLMClient  enabled={self.enabled}  model={self.model!r}"
                 f"  base_url={self.base_url or '(not set — heuristic mode)'}")

    # ── Public API ────────────────────────────────────────────

    async def perceive_screenshot(
        self,
        screenshot_b64: str | None,
    ) -> str:
        """
        Phase 1 of the explore-exploit loop.

        Ask the VLM to describe the current screenshot as a 4×4 grid
        (16 cells, R1C1 top-left → R4C4 bottom-right).  No tools are
        offered — the model just returns a textual description.

        The description is then fed into decide_action() so the model
        has explicit knowledge of what is on screen before choosing an
        action, preventing blind copying of system-prompt examples.

        Returns "" when VLM is disabled or the call fails.
        """
        if not self.enabled or not screenshot_b64:
            return ""
        try:
            return await self._perceive_grid(screenshot_b64)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"perceive_screenshot failed ({exc})")
            return ""

    # ── 4×4 grid perception ───────────────────────────────────

    async def _perceive_grid(self, screenshot_b64: str) -> str:
        """
        Crop the screenshot into 16 equal cells (4 cols × 4 rows),
        fire one VLM call per cell in parallel, then collate the
        results into a structured spatial description.

        We do the cropping ourselves so the pixel-to-cell mapping is
        exact and unambiguous — the model never has to "imagine" the grid.
        """
        import base64
        import io
        from PIL import Image

        img_bytes = base64.b64decode(screenshot_b64)
        img       = Image.open(io.BytesIO(img_bytes))
        W, H      = img.size   # typically 672 × 434

        COLS, ROWS = 4, 4
        cell_w     = W / COLS
        cell_h     = H / ROWS

        # Build cell descriptors
        # Upscale each crop 2× before encoding so the VLM gets more pixels
        # per cell and hallucination on compressed 168×108 crops is reduced.
        UPSCALE = 2

        cells: list[tuple[str, int, int, int, int, str]] = []
        for r in range(ROWS):
            for c in range(COLS):
                x0 = int(c * cell_w)
                y0 = int(r * cell_h)
                x1 = min(int((c + 1) * cell_w), W)
                y1 = min(int((r + 1) * cell_h), H)

                crop = img.crop((x0, y0, x1, y1))
                uw   = (x1 - x0) * UPSCALE
                uh   = (y1 - y0) * UPSCALE
                crop = crop.resize((uw, uh), Image.NEAREST)
                buf  = io.BytesIO()
                crop.save(buf, format="PNG")
                cell_b64 = base64.b64encode(buf.getvalue()).decode()

                label = f"R{r + 1}C{c + 1}"
                cells.append((label, x0, y0, x1, y1, cell_b64))

        log.debug(
            f"perceive_grid  img={W}x{H}  cells={len(cells)}  "
            f"cell_size={int(cell_w)}x{int(cell_h)}"
        )

        # Query each cell sequentially so the VLM server isn't flooded
        lines = [f"SCREEN GRID (full image {W}x{H}, 4x4 cells):"]
        for (label, x0, y0, x1, y1, cell_b64) in cells:
            try:
                desc = await asyncio.to_thread(
                    self._sync_perceive_cell, label, x0, y0, x1, y1, cell_b64
                )
            except Exception as exc:  # noqa: BLE001
                log.debug(f"perceive_grid  {label} error: {exc}")
                desc = "(analysis failed)"
            lines.append(f"  {label} [x:{x0}-{x1}, y:{y0}-{y1}]: {desc}")

        collated = "\n".join(lines)
        log.info(f"perceive_grid complete:\n{collated}")
        return collated

    def _sync_perceive_cell(
        self,
        label: str,
        x0: int, y0: int, x1: int, y1: int,
        cell_b64: str,
    ) -> str:
        """
        Ask the VLM to describe a single cropped cell.
        Returns a short plain-text description (≤ 20 words).
        """
        import urllib.request
        import urllib.error

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a screen-reader assistant. "
                    "You will be shown a cropped region of a real macOS desktop screenshot. "
                    "Describe ONLY what is literally visible in the image — do NOT invent content. "
                    "If the region is unclear or empty, say 'empty or unclear'."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Grid cell {label} of a 4x4 grid on a macOS desktop screenshot "
                            f"(this cell covers x:{x0}-{x1}, y:{y0}-{y1} in native screen pixels).\n"
                            "Describe in 5-15 words what UI element or content is literally visible here. "
                            "Name specific apps, buttons, text fields, icons, or menu items. "
                            "Reply with ONLY the description — no label, no prefix."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{cell_b64}"},
                    },
                ],
            },
        ]

        payload = {
            "model":       self.model,
            "messages":    messages,
            "temperature": 0.0,
            "max_tokens":  60,   # 15 words ≈ 20 tokens; 60 is generous
        }

        url  = f"{self.base_url}/chat/completions"
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        log.debug(f"VLM CELL {label}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode(errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {err_body[:120]}") from exc

        content = (body["choices"][0]["message"].get("content") or "").strip()
        log.debug(f"VLM CELL {label}: {content!r}")
        return content

    async def decide_action(
        self,
        instruction:    str,
        history:        list[dict] | None = None,
        screenshot_b64: str | None = None,
        ui_elements:    str | None = None,
        perception:     str | None = None,
        is_reflection:  bool = False,
    ) -> VLMDecision:
        """
        Ask the VLM for the next (thought, action) step.

        `history` is a list of compact step dicts from the agent loop:
          [{step, thought, action, args, result_ok, eval_ok}, …]

        Falls back to keyword heuristic when VLM is not configured or errors.
        """
        if not self.enabled:
            log.debug(f"VLM not configured — using heuristic  instruction={instruction[:50]!r}")
            return self._heuristic(instruction, is_reflection, history or [])

        try:
            return await asyncio.to_thread(
                self._sync_call, instruction, history or [], screenshot_b64,
                ui_elements, perception, is_reflection
            )
        except Exception as exc:
            log.warning(f"VLM call failed ({exc}) — falling back to heuristic")
            return self._heuristic(instruction, is_reflection, history or [])

    # ── JSON extraction helper ────────────────────────────────

    @staticmethod
    def _iter_json_candidates(text: str):
        """
        Yield candidate JSON substrings from `text`, most-specific first.

        Strategy:
        1. Try the whole string (catches perfectly clean model output).
        2. Walk left-to-right, finding every '{' and trying to parse a
           balanced-brace object starting from there — longest first so
           nested {"name": "open_app", "args": {"name": "Safari"}} is
           returned before the inner {"name": "Safari"}.
        """
        yield text   # try whole thing first

        # Find all '{' positions, collect balanced spans
        spans: list[tuple[int, int]] = []
        for start in range(len(text)):
            if text[start] != '{':
                continue
            depth = 0
            for end in range(start, len(text)):
                if text[end] == '{':
                    depth += 1
                elif text[end] == '}':
                    depth -= 1
                    if depth == 0:
                        spans.append((start, end + 1))
                        break

        # Longest span first (outer objects before inner ones)
        spans.sort(key=lambda s: -(s[1] - s[0]))
        for start, end in spans:
            candidate = text[start:end]
            if candidate != text:   # skip duplicate of the full-text attempt
                yield candidate

    @staticmethod
    def _repair_json(text: str) -> str:
        """
        Apply lightweight heuristic repairs to malformed JSON that VLMs commonly emit.

        Patterns fixed:
        - Missing opening quote on a key:  {x": 1}  →  {"x": 1}
        - Unquoted keys:                   {x: 1}   →  {"x": 1}
        - Trailing commas before } or ]:  {a:1,}   →  {a:1}
        """
        s = text
        # Fix missing opening quote on keys: ([{,] whitespace) WORD" : → $1"WORD":
        s = re.sub(r'([{,]\s*)([A-Za-z_]\w*)"(\s*:)', r'\1"\2"\3', s)
        # Fix fully unquoted keys: ([{,] whitespace) WORD : → $1"WORD":
        s = re.sub(r'([{,]\s*)([A-Za-z_]\w*)(\s*:)', r'\1"\2"\3', s)
        # Remove trailing commas before closing brace/bracket
        s = re.sub(r',\s*([}\]])', r'\1', s)
        return s

    # ── Sync API call (run in thread pool) ───────────────────

    def _sync_call(
        self,
        instruction:    str,
        history:        list[dict],
        screenshot_b64: str | None,
        ui_elements:    str | None,
        perception:     str | None,
        is_reflection:  bool,
    ) -> VLMDecision:
        import urllib.request
        import urllib.error

        messages = self._build_messages(instruction, history, screenshot_b64, ui_elements, perception, is_reflection)

        # mlx_vlm.server DOES support tool calling for Qwen2.5-VL.
        # It auto-detects the json_tools parser from the model's chat template
        # (markers: <tool_call> + tool_call.name) and:
        #   1. Injects the COMPUTER_TOOLS schema into the system prompt
        #   2. The model responds inside <tool_call>{"name":...,"arguments":...}</tool_call>
        #   3. The server parses that into message.tool_calls[0]
        payload = {
            "model":       self.model,
            "messages":    messages,
            "tools":       COMPUTER_TOOLS,
            "tool_choice": "auto",
            "temperature": 0.0,
            # Cap output tokens so a long <think> block can't exhaust the budget
            # before the model emits the actual tool call (finish_reason='length')
            "max_tokens":  2048,
        }

        url  = f"{self.base_url}/chat/completions"
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        log.debug(f"VLM POST {url}  model={self.model}  reflection={is_reflection}")

        # Log the full messages payload (strip image bytes so it's readable)
        if log.isEnabledFor(logging.DEBUG):
            def _redact(msgs: list) -> list:
                out = []
                for m in msgs:
                    if isinstance(m.get("content"), list):
                        parts = []
                        for p in m["content"]:
                            if p.get("type") == "image_url":
                                b64 = (p.get("image_url") or {}).get("url", "")
                                kb  = len(b64) * 3 // 4 // 1024
                                parts.append({"type": "image_url", "image_url": f"<{kb}KB PNG>"})
                            else:
                                parts.append(p)
                        out.append({**m, "content": parts})
                    else:
                        out.append(m)
                return out

            log.debug(
                "VLM messages:\n%s",
                json.dumps(_redact(messages), indent=2, ensure_ascii=True)
            )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode(errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {err_body[:300]}") from exc

        choice  = body["choices"][0]
        message = choice["message"]

        usage = body.get("usage", {})
        log.debug(
            f"VLM response finish_reason={choice.get('finish_reason')!r}  "
            f"tokens: prompt={usage.get('prompt_tokens','?')}  "
            f"completion={usage.get('completion_tokens','?')}"
        )

        # Extract thought from the content field (<think>…</think> or plain prefix)
        raw_content = message.get("content") or ""
        think_m     = re.search(r"<think>(.*?)</think>", raw_content, re.DOTALL)
        thought     = think_m.group(1).strip() if think_m else ""

        # ── Structured tool call ──────────────────────────────
        if message.get("tool_calls"):
            tc   = message["tool_calls"][0]
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments", "{}"))
            except (json.JSONDecodeError, ValueError):
                args = {}
            log.info(f"VLM → tool call: {name}({args})")
            return VLMDecision(name, args, thought=thought)

        # ── Text response (model returned text instead of a tool call) ────────
        content = raw_content
        log.debug(f"VLM text response (len={len(content)}): {content[:200]!r}")

        # Strip <think>…</think> blocks before parsing for action
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        # qwen3-vl sometimes wraps the call in <tool_call>{…}</tool_call>
        xml_m = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content, re.DOTALL)
        if xml_m:
            try:
                d    = json.loads(xml_m.group(1))
                name = d.get("name") or d.get("tool")
                args = d.get("arguments") or d.get("args") or {}
                if isinstance(args, str):
                    args = json.loads(args)
                if name:
                    log.info(f"VLM → XML tool call: {name}({args})")
                    return VLMDecision(name, args, thought=thought)
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        # Bare JSON block  ```json { … } ```
        json_m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_m:
            try:
                d    = json.loads(json_m.group(1))
                name = d.get("name") or d.get("tool") or d.get("function")
                args = d.get("arguments") or d.get("args") or d.get("parameters") or {}
                if isinstance(args, str):
                    args = json.loads(args)
                if name:
                    log.info(f"VLM → JSON block call: {name}({args})")
                    return VLMDecision(name, args, thought=thought)
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        # Bare JSON object — try full content first (handles nested JSON like
        # {"name": "open_app", "args": {"name": "Safari"}} correctly).
        # _repair_json() is applied first to fix common VLM output quirks before parsing.
        for _candidate in self._iter_json_candidates(content.strip()):
            for _text in (_candidate, self._repair_json(_candidate)):
                try:
                    d = json.loads(_text)
                    if not isinstance(d, dict):
                        continue
                    name = d.get("name") or d.get("tool") or d.get("function")
                    args = d.get("args") or d.get("arguments") or {}
                    if isinstance(args, str):
                        args = json.loads(args)
                    if name:
                        log.info(f"VLM → bare JSON call: {name}({args})")
                        return VLMDecision(name, args, thought=thought)
                except (json.JSONDecodeError, ValueError, KeyError):
                    pass

        # Single-line JSON without quotes on key names (relaxed parse)
        # e.g.  {name: "key_press", args: {keys: ["cmd","l"]}}
        try:
            # Try wrapping unquoted keys
            relaxed = re.sub(r'(\{|,)\s*([a-zA-Z_]\w*)\s*:', r'\1"\2":', content.strip())
            d = json.loads(relaxed)
            name = d.get("name") or d.get("tool")
            if name:
                args = d.get("args") or d.get("arguments") or {}
                log.info(f"VLM → relaxed JSON call: {name}({args})")
                return VLMDecision(name, args, thought=thought)
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass

        return self._parse_text(content, instruction, thought)

    # ── Message builder ───────────────────────────────────────

    def _build_messages(
        self,
        instruction:    str,
        history:        list[dict],   # [{step, thought, action, args, result_ok, eval_ok}]
        screenshot_b64: str | None,
        ui_elements:    str | None,
        perception:     str | None,
        is_reflection:  bool,
    ) -> list[dict]:
        """
        Build the messages list for the VLM.

        System prompt carries the full task instruction.
        User turn carries:
          1. Compact text history of recent steps.
          2. (Optional) UI element list from macOS Accessibility API.
          3. Current screenshot image.
        """
        system = (
            "You are a computer-use agent controlling a macOS desktop.\n"
            "You complete tasks by observing screenshots and calling exactly one tool per turn.\n\n"
            f"TASK: {instruction}\n\n"
            "HOW TO READ YOUR CONTEXT:\n"
            "Before this message you will see a SCREEN GRID ANALYSIS — a 4x4 cell breakdown\n"
            "of the current screenshot produced by carefully cropping the image into 16 regions.\n"
            "Each cell entry is: RrCc [x:X0-X1, y:Y0-Y1]: <what is visible there>\n"
            "READ this grid carefully first. It tells you EXACTLY which apps, windows, and UI\n"
            "elements are visible and where. Use it to determine your next action.\n\n"
            "DECISION RULES (apply after reading the grid):\n"
            "1. If the required app does NOT appear in any grid cell -> call open_app first.\n"
            "2. If the required app IS visible in a cell -> interact with it directly.\n"
            "   - Browser address bar is typically in R1 or R2, near the top of the browser.\n"
            "   - To navigate: key_press ['cmd','l'] -> type_text URL -> key_press ['return']\n"
            "3. Call EXACTLY ONE tool per turn.\n"
            "4. If an action had no visible effect, try a DIFFERENT action.\n"
            "5. When the FULL task is visually confirmed on screen, call finished.\n\n"
            "COORDINATE SPACE:\n"
            "The screenshot is sent at native resolution (e.g. 1728x1117 on a MacBook Pro).\n"
            "All x/y coordinates you output must be in the same pixel space as the screenshot.\n"
            "Use the exact pixel ranges from the SCREEN GRID cells to aim clicks.\n\n"
            "You MUST respond with ONLY a JSON object on one line - no explanation, no markdown:\n"
            "{\"name\": \"tool_name\", \"args\": {\"key\": \"value\"}}\n"
            "Example for opening Safari: {\"name\": \"open_app\", \"args\": {\"name\": \"Safari\"}}"
        )
        messages: list[dict] = [{"role": "system", "content": system}]

        # Format history as compact text (no image data in history)
        # Use only ASCII characters to avoid Ollama JSON parsing issues.
        if history:
            lines = []
            for h in history:
                args_str     = ", ".join(f"{k}={v!r}" for k, v in h.get("args", {}).items())
                ok_sym       = "OK" if h.get("result_ok") else "FAIL"
                eval_sym     = "changed" if h.get("eval_ok") else "no-change"
                thought_prev = h.get("thought", "")[:80].replace("\n", " ")
                if thought_prev:
                    lines.append(
                        f"Step {h['step']}: [{thought_prev}]"
                        f" -> {h['action']}({args_str}) [{ok_sym}] eval:[{eval_sym}]"
                    )
                else:
                    lines.append(
                        f"Step {h['step']}: {h['action']}({args_str}) [{ok_sym}] eval:[{eval_sym}]"
                    )
            history_text = "\n".join(lines)
        else:
            history_text = "(first step - no actions yet)"

        # Compose the user turn  — keep everything plain ASCII
        if is_reflection and history:
            last     = history[-1]
            args_str = ", ".join(f"{k}={v!r}" for k, v in last.get("args", {}).items())
            preamble = (
                f"Step history so far:\n{history_text}\n\n"
                f"REFLECTION: '{last['action']}({args_str})' had no visible effect.\n"
                "Try a completely different approach. Suggestions:\n"
                "- To focus a browser address bar: use key_press(['cmd','l'])\n"
                "- If a click missed: look for the correct element in the screenshot\n"
                "- If typing: click the input field first to focus it\n"
                "- If stuck: try key_press(['cmd','r']) to reload, or use open_app again\n\n"
                "Current screenshot:"
            )
        else:
            preamble = (
                f"Step history so far:\n{history_text}\n\n"
                "Current screenshot - decide and call the next tool:"
            )

        user_content: list[dict] = [{"type": "text", "text": preamble}]

        # Phase 1 grid perception — screenshot was physically cropped into 16 cells
        # and each cell was individually described by the VLM.  The pixel ranges
        # are exact so the decide call can use them as targeting coordinates.
        if perception:
            perception_block = (
                perception   # "SCREEN GRID (full image WxH, 4x4 cells):\n  R1C1 [x:..., y:...]: ..."
                + "\n\nBased on the grid above: identify which cells contain the required app or UI element, "
                "then decide your next action using those exact pixel coordinates."
            )
            user_content.append({"type": "text", "text": perception_block})

        # UI element grounding block — precise positions for every interactive
        # element in the frontmost window, already in screenshot coordinate space.
        if ui_elements:
            ui_block = (
                "DETECTED UI ELEMENTS (coordinates in screenshot space 672x434):\n"
                + ui_elements
                + "\nUse these exact coordinates when clicking or targeting elements."
            )
            user_content.append({"type": "text", "text": ui_block})

        if screenshot_b64:
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{screenshot_b64}",
                },
            })

        messages.append({"role": "user", "content": user_content})
        return messages

    # ── Text-response parser ──────────────────────────────────

    def _parse_text(self, content: str, instruction: str, thought: str) -> VLMDecision:
        """
        Last-resort text parser when the model returned plain text instead of
        a tool call (common with mlx_vlm which doesn't honour tool_choice).

        Tries, in order:
          1. JSON fenced block
          2. Natural-language tool descriptions like "key_press with keys=[...]"
          3. Terminal keywords (finished / failed)
          4. Keyword heuristic fallback
        """
        low = content.lower()

        # ── 1. JSON fenced block ──────────────────────────────────────────────
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if m:
            try:
                d    = json.loads(m.group(1))
                name = d.get("name") or d.get("tool") or d.get("function")
                if name:
                    args = d.get("args") or d.get("arguments") or d.get("parameters") or {}
                    return VLMDecision(name, args, thought=thought)
            except (json.JSONDecodeError, ValueError):
                pass

        # ── 2. Natural-language tool descriptions (mlx_vlm style) ────────────
        # e.g.  "key_press with keys=['cmd', 'l']"
        #        "open_app with name='Safari'"
        #        "type_text with text='weather'"
        #        "click with x=100 y=200"
        #        "scroll with x=300 y=400 dy=-3"
        tool_names = [
            "key_press", "hotkey", "type_text", "click", "left_double",
            "right_single", "scroll", "drag", "move_mouse", "wait",
            "open_app", "screenshot", "finished", "failed", "call_user",
        ]
        for tool in tool_names:
            if tool in low:
                # Try to extract args from the surrounding text
                args: dict = {}

                # keys=[...] list
                km = re.search(r"keys\s*=\s*\[([^\]]+)\]", content)
                if km:
                    raw_keys = [k.strip().strip("'\"") for k in km.group(1).split(",")]
                    args["keys"] = raw_keys

                # name='...'
                nm = re.search(r"\bname\s*=\s*['\"]([^'\"]+)['\"]", content)
                if nm:
                    args["name"] = nm.group(1)

                # text='...'
                tm = re.search(r"\btext\s*=\s*['\"]([^'\"]*)['\"]", content)
                if tm:
                    args["text"] = tm.group(1)

                # x=NNN  y=NNN
                xm = re.search(r"\bx\s*=\s*(\d+)", content)
                ym = re.search(r"\by\s*=\s*(\d+)", content)
                if xm:
                    args["x"] = int(xm.group(1))
                if ym:
                    args["y"] = int(ym.group(1))

                # dy=NNN  dx=NNN
                dym = re.search(r"\bdy\s*=\s*(-?\d+)", content)
                dxm = re.search(r"\bdx\s*=\s*(-?\d+)", content)
                if dym:
                    args["dy"] = int(dym.group(1))
                if dxm:
                    args["dx"] = int(dxm.group(1))

                # ms=NNN
                msm = re.search(r"\bms\s*=\s*(\d+)", content)
                if msm:
                    args["ms"] = int(msm.group(1))

                # summary / reason / question
                for field in ("summary", "reason", "question"):
                    fm = re.search(rf"\b{field}\s*=\s*['\"]([^'\"]*)['\"]", content)
                    if fm:
                        args[field] = fm.group(1)

                log.info(f"VLM -> text-parsed tool: {tool}({args})")
                return VLMDecision(tool, args, thought=thought)

        # ── 3. Terminal keywords ──────────────────────────────────────────────
        if any(w in low for w in ("task complete", "successfully completed", "done")):
            return VLMDecision("finished", {"summary": content[:200]}, thought=thought)
        if any(w in low for w in ("cannot", "unable", "not found", "impossible")):
            return VLMDecision("failed", {"reason": content[:200]}, thought=thought)

        # ── 4. Give up → heuristic ────────────────────────────────────────────
        log.debug(f"_parse_text: no pattern matched for {content[:80]!r} — using heuristic")
        return self._heuristic(instruction, is_reflection=False, history=[])

    # ── Heuristic fallback ────────────────────────────────────

    def _heuristic(
        self,
        instruction:   str,
        is_reflection: bool,
        history:       list[dict],
    ) -> VLMDecision:
        """
        Keyword-based decision used when the VLM is not configured or errors.
        Uses compact history dicts [{action, result_ok, eval_ok, …}].
        """
        import random

        low = instruction.lower()

        # If we have successful history, check if we should wrap up
        if history:
            last = history[-1]
            # All recent steps succeeded: declare finished
            if len(history) >= 3 and all(h.get("eval_ok") for h in history[-3:]):
                return VLMDecision("finished", {"summary": "Actions performed — task assumed complete"})
            # Last action was open_app and succeeded
            if last.get("action") == "open_app" and last.get("result_ok"):
                app = last.get("args", {}).get("name", "app")
                return VLMDecision("finished", {"summary": f"{app} opened successfully"})

        # Open an app
        known_apps = [
            "safari", "chrome", "firefox", "itunes", "music", "finder",
            "terminal", "calculator", "notes", "mail", "slack", "xcode",
            "notion", "zoom", "discord", "vscode", "code", "spotify",
        ]
        for app in known_apps:
            if app in low:
                if any(w in low for w in ("open", "launch", "start")):
                    return VLMDecision("open_app", {"name": app.title()})

        open_m = re.search(r"(?:open|launch|start)\s+([a-z0-9 ]+?)(?:\s+and|\s+to|$)", low)
        if open_m:
            return VLMDecision("open_app", {"name": open_m.group(1).strip().title()})

        # Navigation / interaction heuristics
        if any(w in low for w in ("spotlight", "cmd+space", "command space")):
            return VLMDecision("key_press", {"keys": ["cmd", "space"]})
        if any(w in low for w in ("type", "write", "input", "enter text", "search for")):
            query = re.sub(r".*(type|write|input|search for)\s+", "", low).strip()
            return VLMDecision("type_text", {"text": query or instruction})
        if "return" in low or "submit" in low:
            return VLMDecision("key_press", {"keys": ["return"]})
        if any(w in low for w in ("scroll down",)):
            return VLMDecision("scroll", {"x": 640, "y": 400, "dy": 200})
        if any(w in low for w in ("scroll up",)):
            return VLMDecision("scroll", {"x": 640, "y": 400, "dy": -200})
        if "wait" in low:
            return VLMDecision("wait", {"ms": 1500})
        if any(w in low for w in ("click", "press", "tap", "button")):
            return VLMDecision("click", {"x": random.randint(300, 700), "y": random.randint(200, 600)})

        return VLMDecision("screenshot", {})


__all__ = ["VLMClient", "VLMDecision", "COMPUTER_TOOLS"]
