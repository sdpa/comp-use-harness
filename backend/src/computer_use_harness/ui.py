from __future__ import annotations

from typing import Any


class DesktopShell:
    """Python-side compatibility wrapper for the Electron desktop UI.

    The actual end-user interface is created in the Electron app under the
    `electron/` directory. This shell remains as a small compatibility shim so the
    backend can expose status updates and keep the desktop shell boundary clean.
    """

    def __init__(self, title: str = "Computer-Use Harness") -> None:
        self.title = title
        self.status: dict[str, Any] = {}

    def update_status(self, **kwargs: Any) -> None:
        self.status.update(kwargs)
        print(f"[{self.title}] {self.status}")

    def show(self) -> None:
        print(
            f"[{self.title}] Electron desktop shell is the UI front-end. "
            "Run `npm start` from the repository root to launch it."
        )


if __name__ == "__main__":
    app = DesktopShell()
    app.update_status(state="ready", plan_count=3)
    app.show()
