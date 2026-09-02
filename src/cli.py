"""Local CLI for dry-run and end-to-end execution against remote D1."""

import asyncio

from cli.main import main

if __name__ == "__main__":
    asyncio.run(main())
