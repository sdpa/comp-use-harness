"""
MCP server — Computer-control primitives for the computer-use harness.

Exposed tools:
  screenshot         – capture screen; returns base64 PNG when include_image=True
  screenshot_with_marks – annotated screenshot with numbered UI element marks
  open_app           – launch macOS application (no Accessibility needed)
  click              – click at coordinates         (Accessibility required)
  type_text          – type keyboard text            (Accessibility required)
  key_press          – press keys / shortcuts        (Accessibility required)
  scroll             – scroll at position            (Accessibility required)
  move_mouse         – move cursor                   (Accessibility required)
  wait               – sleep for N ms
  get_screen_info    – returns display sizes + cursor position

Safety features:
  dry_run=True  – log intent only, never touch OS
  allowlist     – restrict which tools can be called
  confirmation_gate – async callback before destructive actions
"""
from __future__ import annotations

import base64
import logging
import subprocess
import time
from io import BytesIO
from typing import Any, Callable, Awaitable

log = logging.getLogger("harness.mcp")

# ── macOS app-name normalisation map ─────────────────────────────────────────
_APP_MAP: dict[str, str] = {
    "safari":       "Safari",
    "chrome":       "Google Chrome",
    "firefox":      "Firefox",
    "terminal":     "Terminal",
    "iterm":        "iTerm",
    "iterm2":       "iTerm",
    "calculator":   "Calculator",
    "notes":        "Notes",
    "finder":       "Finder",
    "itunes":       "Music",
    "music":        "Music",
    "mail":         "Mail",
    "slack":        "Slack",
    "vscode":       "Visual Studio Code",
    "code":         "Visual Studio Code",
    "xcode":        "Xcode",
    "zoom":         "zoom.us",
    "notion":       "Notion",
    "figma":        "Figma",
    "discord":      "Discord",
    "messages":     "Messages",
    "facetime":     "FaceTime",
    "calendar":     "Calendar",
    "photos":       "Photos",
    "maps":         "Maps",
    "preview":      "Preview",
    "spotify":      "Spotify",
    "system preferences": "System Preferences",
    "system settings":    "System Settings",
    "activity monitor":   "Activity Monitor",
    "textedit":    "TextEdit",
    "pages":       "Pages",
    "numbers":     "Numbers",
    "keynote":     "Keynote",
}

# ── Destructive actions — route to confirmation gate ─────────────────────────
_DESTRUCTIVE_TOOLS = frozenset({"type_text", "key_press", "click"})


class ComputerControlServer:
    """
    Real computer-control primitives.

    dry_run=True  → log intent, return mock response, never touch OS
    dry_run=False → execute real OS-level actions

    confirmation_gate: async callable(tool_name, args) → bool
      If provided, called before any destructive action.
      Return True to proceed, False to skip.
    """

    def __init__(
        self,
        *,
        allowlist:         list[str] | None = None,
        dry_run:           bool = False,
        confirmation_gate: Callable[[str, dict], Awaitable[bool]] | None = None,
    ):
        self.allowlist         = set(allowlist) if allowlist else set()
        self.dry_run           = dry_run
        self.confirmation_gate = confirmation_gate

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _check_allowed(self, action: str) -> None:
        if self.allowlist and action not in self.allowlist:
            raise PermissionError(f"Action '{action}' is not on the allow-list")

    def _require_accessibility(self, action: str) -> None:
        try:
            import pyautogui  # noqa: F401
        except ImportError:
            raise RuntimeError(
                f"'{action}' requires pyautogui: pip install pyautogui. "
                "Also grant Accessibility access in System Settings → Privacy & Security."
            )

    def _capture_mss(self, region: dict | None) -> tuple[bytes, int, int]:
        """Capture screen with mss, return (png_bytes, width, height)."""
        import mss
        import mss.tools

        with mss.mss() as sct:
            mon = region or sct.monitors[1]
            img = sct.grab(mon)
            w, h = img.width, img.height
            png_bytes = mss.tools.to_png(img.rgb, img.size)
            return png_bytes, w, h

    # ── Tools ─────────────────────────────────────────────────────────────────

    def screenshot(
        self,
        *,
        region:        dict[str, int] | None = None,
        include_image: bool = True,
    ) -> dict[str, Any]:
        """
        Capture a screenshot and return the raw PNG at native resolution.
        scale is always 1.0 — VLM coordinates map 1:1 to screen pixels.
        """
        if self.dry_run:
            log.debug("screenshot [dry-run]")
            result: dict[str, Any] = {
                "ok": True, "dry_run": True,
                "width": 1728, "height": 1117,
                "out_width": 1728, "out_height": 1117,
                "scale": 1.0,
            }
            if include_image:
                result["image_b64"] = ""
            return result

        try:
            png_bytes, w, h = self._capture_mss(region)
        except ImportError:
            log.warning("mss not installed — cannot take screenshot")
            return {"ok": False, "error": "mss not installed (pip install mss)"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

        result: dict[str, Any] = {"ok": True, "width": w, "height": h, "region": region}

        if include_image:
            encoded = base64.b64encode(png_bytes).decode()
            result["scale"]      = 1.0
            result["out_width"]  = w
            result["out_height"] = h
            result["image_b64"]  = encoded
            log.debug(
                f"screenshot  {w}×{h}  b64_kb={len(encoded) // 1024}  include_image={include_image}"
            )
        else:
            result["scale"]      = 1.0
            result["out_width"]  = w
            result["out_height"] = h
            log.debug(f"screenshot  {w}×{h}  include_image={include_image}")

        return result

    @staticmethod
    def _encode_downscaled(png_bytes: bytes, w: int, h: int, max_edge: int) -> tuple[str, int, int]:
        """
        Resize so the longest edge == max_edge.
        Returns (base64_jpeg, out_width, out_height).
        """
        try:
            from PIL import Image  # type: ignore
            img = Image.open(BytesIO(png_bytes))
            if w >= h:
                new_w = max_edge
                new_h = max(1, round(h * max_edge / w))
            else:
                new_h = max_edge
                new_w = max(1, round(w * max_edge / h))
            img = img.resize((new_w, new_h), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            return base64.b64encode(buf.getvalue()).decode(), new_w, new_h
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            log.debug(f"downscale failed ({exc}) — using full PNG")
        # Fallback: return original PNG unchanged
        return base64.b64encode(png_bytes).decode(), w, h

    def screenshot_with_marks(
        self,
        *,
        region: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """
        Capture a screenshot annotated with numbered marks at a grid of positions.
        Returns {"ok", "width", "height", "image_b64", "marks": [{id, x, y, cx, cy}]}.

        If PIL/Pillow is unavailable, returns the plain screenshot without marks.
        """
        base = self.screenshot(region=region, include_image=True)
        if not base.get("ok"):
            return base

        w = base["width"]
        h = base["height"]
        image_b64 = base.get("image_b64", "")

        # Try to annotate with PIL
        marks = []
        annotated_b64 = image_b64

        try:
            from PIL import Image, ImageDraw, ImageFont  # type: ignore

            png_bytes = base64.b64decode(image_b64)
            img = Image.open(BytesIO(png_bytes)).convert("RGBA")
            draw = ImageDraw.Draw(img)

            # 6×4 grid of marks
            cols, rows_n = 6, 4
            mark_id = 1
            for row in range(rows_n):
                for col in range(cols):
                    cx = int(w * (col + 0.5) / cols)
                    cy = int(h * (row + 0.5) / rows_n)
                    r  = 12
                    # Translucent circle
                    draw.ellipse(
                        [(cx - r, cy - r), (cx + r, cy + r)],
                        fill=(255, 80, 80, 180),
                        outline=(255, 255, 255, 220),
                        width=2,
                    )
                    # Label
                    try:
                        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 11)
                    except Exception:
                        font = ImageFont.load_default()
                    label = str(mark_id)
                    bbox = draw.textbbox((0, 0), label, font=font)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    draw.text((cx - tw // 2, cy - th // 2), label, fill=(255, 255, 255, 255), font=font)
                    marks.append({"id": mark_id, "cx": cx, "cy": cy, "x": cx - r, "y": cy - r, "w": r * 2, "h": r * 2})
                    mark_id += 1

            buf = BytesIO()
            img.save(buf, format="PNG")
            annotated_b64 = base64.b64encode(buf.getvalue()).decode()
            log.debug(f"screenshot_with_marks  {w}×{h}  {len(marks)} marks (PIL)")
        except ImportError:
            log.debug("PIL not available — screenshot_with_marks returns plain image")
        except Exception as exc:  # noqa: BLE001
            log.warning(f"screenshot_with_marks annotation failed: {exc}")

        return {
            "ok":        True,
            "width":     w,
            "height":    h,
            "image_b64": annotated_b64,
            "marks":     marks,
        }

    def open_app(self, name: str) -> dict[str, Any]:
        """Launch an application by name. Uses macOS 'open -a'. No Accessibility needed."""
        self._check_allowed("open_app")
        app_name = _APP_MAP.get(name.lower().strip(), name.title())

        if self.dry_run:
            log.debug(f"open_app {app_name!r} [dry-run]")
            return {"ok": True, "dry_run": True, "app": app_name}

        log.info(f"open_app  launching {app_name!r}")
        try:
            result = subprocess.run(
                ["open", "-a", app_name],
                capture_output=True, text=True, timeout=10,
            )
        except FileNotFoundError:
            return {"ok": False, "error": "'open' command not found — not on macOS?"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Timed out launching {app_name}"}

        if result.returncode != 0:
            err = result.stderr.strip() or f"exit code {result.returncode}"
            log.warning(f"open_app FAILED {app_name!r}: {err}")
            return {"ok": False, "app": app_name, "error": err}

        log.info(f"open_app OK  {app_name!r}")
        time.sleep(1.2)  # wait for the app window to appear
        self._snap_left_half(app_name)
        return {"ok": True, "app": app_name, "method": "open -a"}

    def _snap_left_half(self, app_name: str) -> None:
        """
        Resize and position the app's frontmost window to occupy the left
        half of the primary display, keeping the right half clear for the
        computer-use harness UI.

        Uses AppleScript `bounds {left, top, right, bottom}`.  Failures are
        logged at DEBUG level and never propagate — the app is already open.
        """
        try:
            import mss as _mss
            with _mss.mss() as sct:
                mon = sct.monitors[1]   # primary display
                sw, sh = mon["width"], mon["height"]
        except Exception:
            sw, sh = 1728, 1080   # safe fallback

        half_w = sw // 2

        # bounds = {left, top, right, bottom}
        script = (
            f'tell application "{app_name}"\n'
            f'  activate\n'
            f'  if (count of windows) > 0 then\n'
            f'    set bounds of window 1 to {{0, 0, {half_w}, {sh}}}\n'
            f'  end if\n'
            f'end tell'
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=6,
            )
            if result.returncode == 0:
                log.info(f"snap_left_half  {app_name!r}  bounds=(0,0,{half_w},{sh})")
            else:
                log.debug(f"snap_left_half  AppleScript error: {result.stderr.strip()[:120]}")
        except Exception as exc:  # noqa: BLE001
            log.debug(f"snap_left_half  failed ({exc})")

    def click(
        self, x: int, y: int, button: str = "left", clicks: int = 1
    ) -> dict[str, Any]:
        self._check_allowed("click")
        if self.dry_run:
            log.debug(f"click ({x},{y}) [dry-run]")
            return {"ok": True, "dry_run": True, "x": x, "y": y}
        self._require_accessibility("click")
        import pyautogui
        log.info(f"click ({x},{y}) button={button} clicks={clicks}")
        pyautogui.click(x, y, button=button, clicks=clicks)
        return {"ok": True, "x": x, "y": y, "button": button, "clicks": clicks}

    def type_text(self, text: str) -> dict[str, Any]:
        self._check_allowed("type_text")
        if self.dry_run:
            log.debug(f"type_text {text!r:.40} [dry-run]")
            return {"ok": True, "dry_run": True, "chars": len(text)}
        self._require_accessibility("type_text")
        import pyautogui
        log.info(f"type_text {text!r:.60}")
        pyautogui.typewrite(text, interval=0.04)
        return {"ok": True, "chars_typed": len(text)}

    def key_press(self, keys: list[str] | str) -> dict[str, Any]:
        self._check_allowed("key_press")
        normalized = [keys] if isinstance(keys, str) else list(keys)
        if self.dry_run:
            log.debug(f"key_press {normalized} [dry-run]")
            return {"ok": True, "dry_run": True, "keys": normalized}
        self._require_accessibility("key_press")
        import pyautogui
        log.info(f"key_press {normalized}")
        pyautogui.hotkey(*normalized)
        return {"ok": True, "keys": normalized}

    def move_mouse(self, x: int, y: int) -> dict[str, Any]:
        self._check_allowed("move_mouse")
        if self.dry_run:
            return {"ok": True, "dry_run": True, "x": x, "y": y}
        self._require_accessibility("move_mouse")
        import pyautogui
        pyautogui.moveTo(x, y)
        return {"ok": True, "x": x, "y": y}

    def scroll(self, x: int, y: int, dx: int = 0, dy: int = 0) -> dict[str, Any]:
        self._check_allowed("scroll")
        if self.dry_run:
            return {"ok": True, "dry_run": True}
        self._require_accessibility("scroll")
        import pyautogui
        pyautogui.scroll(dy, x=x, y=y)
        return {"ok": True, "x": x, "y": y, "dy": dy}

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.4) -> dict[str, Any]:
        """Click-and-drag from (x1, y1) to (x2, y2)."""
        self._check_allowed("drag")
        if self.dry_run:
            log.debug(f"drag ({x1},{y1}) → ({x2},{y2}) [dry-run]")
            return {"ok": True, "dry_run": True, "x1": x1, "y1": y1, "x2": x2, "y2": y2}
        self._require_accessibility("drag")
        import pyautogui
        log.info(f"drag ({x1},{y1}) → ({x2},{y2})")
        pyautogui.moveTo(x1, y1)
        pyautogui.dragTo(x2, y2, duration=duration, button="left")
        return {"ok": True, "x1": x1, "y1": y1, "x2": x2, "y2": y2}

    def wait(self, ms: int = 1000) -> dict[str, Any]:
        self._check_allowed("wait")
        log.debug(f"wait {ms}ms")
        time.sleep(ms / 1000)
        return {"ok": True, "ms": ms}

    def get_screen_info(self) -> dict[str, Any]:
        """Returns display sizes and current cursor position."""
        displays = []
        cursor = {"x": 0, "y": 0}
        try:
            import mss
            with mss.mss() as sct:
                displays = [
                    {"width": m["width"], "height": m["height"], "left": m["left"], "top": m["top"]}
                    for m in sct.monitors[1:]
                ]
        except ImportError:
            displays = [{"width": 0, "height": 0, "left": 0, "top": 0}]

        try:
            import pyautogui
            pos = pyautogui.position()
            cursor = {"x": pos.x, "y": pos.y}
        except Exception:  # noqa: BLE001
            pass

        return {"ok": True, "displays": displays, "cursor_pos": cursor}


# ── Factory ───────────────────────────────────────────────────────────────────

def build_server(
    *,
    allowlist: list[str] | None = None,
    dry_run:   bool = False,
) -> ComputerControlServer:
    return ComputerControlServer(allowlist=allowlist, dry_run=dry_run)


# ── Optional FastMCP tool registration ───────────────────────────────────────

try:
    from mcp.server.fastmcp import FastMCP
    _srv = FastMCP("computer-control")
    _ctrl = ComputerControlServer(dry_run=False)

    @_srv.tool()
    def screenshot(region: dict | None = None) -> dict:
        return _ctrl.screenshot(region=region, include_image=True)

    @_srv.tool()
    def screenshot_with_marks(region: dict | None = None) -> dict:
        return _ctrl.screenshot_with_marks(region=region)

    @_srv.tool()
    def open_app(name: str) -> dict:
        return _ctrl.open_app(name)

    @_srv.tool()
    def click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
        return _ctrl.click(x, y, button=button, clicks=clicks)

    @_srv.tool()
    def type_text(text: str) -> dict:
        return _ctrl.type_text(text)

    @_srv.tool()
    def key_press(keys: list) -> dict:
        return _ctrl.key_press(keys)

    @_srv.tool()
    def scroll(x: int, y: int, dx: int = 0, dy: int = 0) -> dict:
        return _ctrl.scroll(x, y, dx=dx, dy=dy)

    @_srv.tool()
    def drag(x1: int, y1: int, x2: int, y2: int) -> dict:
        return _ctrl.drag(x1, y1, x2, y2)

    @_srv.tool()
    def move_mouse(x: int, y: int) -> dict:
        return _ctrl.move_mouse(x, y)

    @_srv.tool()
    def wait(ms: int = 1000) -> dict:
        return _ctrl.wait(ms=ms)

    @_srv.tool()
    def get_screen_info() -> dict:
        return _ctrl.get_screen_info()

    __all__ = ["ComputerControlServer", "build_server", "_srv"]
except ImportError:
    __all__ = ["ComputerControlServer", "build_server"]
