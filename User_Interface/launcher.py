"""PyInstaller entry point with package-absolute imports."""

import sys


if "--version" in sys.argv:
    from fdem_controller import __version__

    print(f"FDEM TX Controller {__version__}")
    raise SystemExit(0)

if "--smoke-gui" in sys.argv:
    from fdem_controller.app import FdemControllerApp

    smoke_app = FdemControllerApp()
    smoke_app.withdraw()
    smoke_app.after(150, smoke_app._shutdown_now)
    smoke_app.mainloop()
    raise SystemExit(0)

from fdem_controller.app import main

main()
