from __future__ import annotations

import asyncio
import signal

from .engine import ResearchWorker
from .migrations import migrate_database


async def main() -> None:
    migrate_database()
    worker = ResearchWorker()
    worker.recover_expired_leases()
    worker.reconcile_incomplete_runs()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, worker.stop)
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
