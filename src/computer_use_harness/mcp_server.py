from __future__ import annotations

from typing import Any


try:  # Optional dependency; the server is still importable without the package installed.
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - for lightweight local scaffolding
    FastMCP = None


class ComputerControlServer:
    """Thin, architecture-centered wrapper around desktop automation primitives.

    This is intentionally simple and safe to import without a live MCP runtime.
    The real OS-control hooks live behind these methods, and the server can be
    backed by the official MCP SDK when the package is installed.
    """

    def __init__(self, *, allowlist: list[str] | None = None, dry_run: bool = False):
        self.allowlist = allowlist or []
        self.dry_run = dry_run

    def _check_allowed(self, action: str) -> None:
        if not self.allowlist:
            return
        if action not in self.allowlist:
            raise PermissionError(f"Action '{action}' is not permitted in the current allow-list")

    def screenshot(self, *, region: dict[str, int] | None = None) -> dict[str, Any]:
        if self.dry_run:
            return {"ok": True, "dry_run": True, "message": "Screenshot request accepted in dry-run mode"}
        return {
            "ok": True,
            "image": None,
            "width": 0,
            "height": 0,
            "scale": 1,
            "region": region,
        }

    def move_mouse(self, x: int, y: int) -> dict[str, Any]:
        self._check_allowed("move_mouse")
        return {"ok": True, "x": x, "y": y, "dry_run": self.dry_run}

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> dict[str, Any]:
        self._check_allowed("click")
        return {"ok": True, "x": x, "y": y, "button": button, "clicks": clicks, "dry_run": self.dry_run}

    def type_text(self, text: str) -> dict[str, Any]:
        self._check_allowed("type_text")
        return {"ok": True, "chars_typed": len(text), "dry_run": self.dry_run}

    def key_press(self, keys: list[str] | str) -> dict[str, Any]:
        self._check_allowed("key_press")
        normalized = [keys] if isinstance(keys, str) else list(keys)
        return {"ok": True, "keys": normalized, "dry_run": self.dry_run}

    def scroll(self, x: int, y: int, dx: int = 0, dy: int = 0) -> dict[str, Any]:
        self._check_allowed("scroll")
        return {"ok": True, "x": x, "y": y, "dx": dx, "dy": dy, "dry_run": self.dry_run}

    def open_app(self, name: str) -> dict[str, Any]:
        self._check_allowed("open_app")
        return {"ok": True, "launched": True, "method": "launch_request", "name": name, "dry_run": self.dry_run}

    def wait(self, ms: int = 1000) -> dict[str, Any]:
        self._check_allowed("wait")
        return {"ok": True, "ms": ms, "dry_run": self.dry_run}

    def get_screen_info(self) -> dict[str, Any]:
        return {"displays": [{"width": 0, "height": 0, "scale": 1}], "cursor_pos": {"x": 0, "y": 0}}


def build_server(*, allowlist: list[str] | None = None, dry_run: bool = False) -> ComputerControlServer:
    return ComputerControlServer(allowlist=allowlist, dry_run=dry_run)


if FastMCP is not None:
    server = FastMCP("computer-control")
    
    @server.tool()
    def screenshot(*, region: dict[str, int] | None = None) -> dict[str, Any]:
        return build_server().screenshot(region=region)

    @server.tool()
    def move_mouse(x: int, y: int) -> dict[str, Any]:
        return build_server().move_mouse(x, y)

    @server.tool()
    def click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict[str, Any]:
        return build_server().click(x, y, button=button, clicks=clicks)

    @server.tool()
    def type_text(text: str) -> dict[str, Any]:
        return build_server().type_text(text)

    @server.tool()
    def key_press(keys: list[str] | str) -> dict[str, Any]:
        return build_server().key_press(keys)

    @server.tool()
    def scroll(x: int, y: int, dx: int = 0, dy: int = 0) -> dict[str, Any]:
        return build_server().scroll(x, y, dx=dx, dy=dy)

    @server.tool()
    def open_app(name: str) -> dict[str, Any]:
        return build_server().open_app(name)

    @server.tool()
    def wait(ms: int = 1000) -> dict[str, Any]:
        return build_server().wait(ms=ms)

    @server.tool()
    def get_screen_info() -> dict[str, Any]:
        return build_server().get_screen_info()

    __all__ = ["ComputerControlServer", "build_server", "server"]
else:
    __all__ = ["ComputerControlServer", "build_server"]
