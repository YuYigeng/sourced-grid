from __future__ import annotations

import asyncio
import signal

from .db import initialize_database
from .engine import ResearchWorker


async def main() -> None:
    initialize_database()
    worker = ResearchWorker()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, worker.stop)
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
