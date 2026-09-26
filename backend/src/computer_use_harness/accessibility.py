"""
accessibility.py — macOS Accessibility API element detection.

Queries the frontmost window for interactive UI elements and returns them
as a compact text block for the VLM context.  Coordinates are converted from
native screen pixels to the downscaled screenshot space so the VLM can use
them directly as tool-call arguments.

Requires:  pip install atomacos
Falls back to empty string if atomacos is not installed or if the Accessibility
permission has not been granted.

Example output:
  AXTextField "" at (2, 14) size (130x11) placeholder="Enter a website name"
  AXButton "Back" at (2, 7) size (7x9)
  AXButton "Forward" at (10, 7) size (7x9)
  AXLink "YouTube" at (7, 46) size (21x7)
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("harness.ax")

# Roles worth reporting — enough to cover every clickable / typeable element
_INTERESTING_ROLES: frozenset[str] = frozenset({
    "AXButton",
    "AXTextField",
    "AXTextArea",
    "AXSearchField",
    "AXLink",
    "AXStaticText",
    "AXMenuItem",
    "AXMenuBarItem",
    "AXCheckBox",
    "AXRadioButton",
    "AXSlider",
    "AXComboBox",
    "AXPopUpButton",
    "AXTab",
    "AXToolbar",
    "AXImage",            # icons that are clickable
})

_MAX_TEXT   = 60   # truncate long labels / values
_MAX_DEPTH  = 6    # tree traversal depth limit
_MAX_ELEMS  = 40   # max elements to return


def get_ui_elements_text(
    scale: float = 1.0,
    max_elements: int = _MAX_ELEMS,
) -> str:
    """
    Return a compact text block describing interactive elements in the
    frontmost window.

    Args:
        scale:  Screenshot-to-native ratio — pre_shot["scale"] (e.g. 0.389).
                Native coordinates are multiplied by this to get screenshot coords.
        max_elements: Hard cap on returned elements.

    Returns:
        Multi-line string, or "" if detection is unavailable / fails.
    """
    try:
        import atomacos  # type: ignore
    except ImportError:
        log.debug("atomacos not installed — UI element detection disabled")
        return ""

    try:
        import signal

        def _timeout_handler(signum, frame):
            raise TimeoutError("atomacos getFrontmostApp timed out")

        # Install a 1.5 s SIGALRM guard (Unix only — harmless on macOS)
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(1)   # 1 second hard limit
        try:
            app = atomacos.getFrontmostApp()
        finally:
            signal.alarm(0)                        # cancel alarm
            signal.signal(signal.SIGALRM, old_handler)  # restore handler
        if app is None:
            log.debug("ax: getFrontmostApp returned None")
            return ""

        # Prefer the focused window; fall back to first visible window
        win: Any = None
        try:
            win = app.AXFocusedWindow
        except Exception:
            pass
        if win is None:
            try:
                windows = app.AXWindows
                if windows:
                    win = windows[0]
            except Exception:
                pass
        if win is None:
            log.debug("ax: no window found")
            return ""

        collected: list[tuple] = []
        _collect(win, collected, max_elements, depth=0)

        if not collected:
            return ""

        lines: list[str] = []
        for role, title, value, placeholder, nx, ny, nw, nh in collected:
            # Convert native → screenshot coordinate space
            sx = round(nx * scale)
            sy = round(ny * scale)
            sw = round(nw * scale)
            sh = round(nh * scale)

            parts = [role]
            label = title or value
            if label:
                parts.append(f'"{label[:_MAX_TEXT]}"')
            parts.append(f"at ({sx}, {sy}) size ({sw}x{sh})")
            if not label and placeholder:
                parts.append(f'placeholder="{placeholder[:_MAX_TEXT]}"')
            elif title and value:
                parts.append(f'value="{value[:_MAX_TEXT]}"')
            lines.append(" ".join(parts))

        log.debug(f"ax: {len(lines)} elements from frontmost window")
        return "\n".join(lines)

    except Exception as exc:  # noqa: BLE001
        log.debug(f"ax: detection failed ({exc})")
        return ""


def _collect(
    element: Any,
    results: list[tuple],
    max_count: int,
    depth: int,
) -> None:
    """Depth-first traversal; appends (role, title, value, placeholder, x, y, w, h)."""
    if len(results) >= max_count or depth > _MAX_DEPTH:
        return

    try:
        role = getattr(element, "AXRole", None)
        if role in _INTERESTING_ROLES:
            pos  = getattr(element, "AXPosition", None)
            size = getattr(element, "AXSize",     None)
            if pos is not None and size is not None:
                title       = str(getattr(element, "AXTitle",            "") or "")
                value       = str(getattr(element, "AXValue",            "") or "")
                placeholder = str(getattr(element, "AXPlaceholderValue", "") or "")
                x, y = float(pos[0]), float(pos[1])
                w, h = float(size[0]), float(size[1])
                # Skip zero-size or off-screen elements
                if w > 0 and h > 0 and x >= 0 and y >= 0:
                    results.append((role, title, value, placeholder, x, y, w, h))

        children = getattr(element, "AXChildren", None) or []
        for child in children:
            if len(results) >= max_count:
                break
            _collect(child, results, max_count, depth + 1)

    except Exception:  # noqa: BLE001
        pass  # silently skip inaccessible elements


__all__ = ["get_ui_elements_text"]
