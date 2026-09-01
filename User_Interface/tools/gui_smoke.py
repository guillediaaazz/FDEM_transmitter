"""Exercise one real CustomTkinter main-loop cycle without showing a window."""

from __future__ import annotations

import types

import fdem_controller.app as app_module
from fdem_controller.settings import AppSettings


def main() -> None:
    store = types.SimpleNamespace(
        load=lambda: AppSettings(language="en"),
        save=lambda _settings: None,
    )
    app_module.SettingsStore = lambda: store
    app = app_module.FdemControllerApp()
    app.withdraw()
    if not callable(app.state):
        raise TypeError("Tk state() was shadowed by an application attribute")
    app.after(100, app._shutdown_now)
    app.mainloop()
    print("GUI main-loop smoke test passed")


if __name__ == "__main__":
    main()

