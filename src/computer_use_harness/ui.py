from __future__ import annotations

from typing import Any


class DesktopShell:
    """Small desktop shell placeholder for viewing task progress.

    This is intentionally lightweight and does not depend on Electron. If a
    graphical environment is present, the app tries to open a basic Tkinter
    window; otherwise the status is just printed to stdout.
    """

    def __init__(self, title: str = "Computer-Use Harness") -> None:
        self.title = title
        self.status: dict[str, Any] = {}

    def update_status(self, **kwargs: Any) -> None:
        self.status.update(kwargs)
        print(f"[{self.title}] {self.status}")

    def show(self) -> None:
        try:
            import tkinter as tk
        except Exception:  # pragma: no cover - non-graphical environment fallback
            print(f"[{self.title}] GUI unavailable; shell started in console mode")
            return

        root = tk.Tk()
        root.title(self.title)
        label = tk.Label(root, text="Computer-Use Harness is running", padx=20, pady=20)
        label.pack()
        root.mainloop()


if __name__ == "__main__":
    app = DesktopShell()
    app.update_status(state="ready", plan_count=3)
    app.show()
