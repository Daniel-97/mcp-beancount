"""Allow running the package with ``python -m beancount_mcp``."""

from beancount_mcp.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
