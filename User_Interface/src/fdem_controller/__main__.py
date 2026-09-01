import sys


if __name__ == "__main__":
    # Keep the packaged smoke/version path independent of Tk and WinRT imports.
    if "--version" in sys.argv:
        from . import __version__

        print(f"FDEM TX Controller {__version__}")
        raise SystemExit(0)

    from .app import main

    main()
