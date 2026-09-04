"""``python -m apps.api`` -> the admin CLI (create-user / set-password)."""

from apps.api.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
