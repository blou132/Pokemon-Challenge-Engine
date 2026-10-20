"""PyInstaller script entrypoint; package-relative resource paths remain intact."""
from app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
