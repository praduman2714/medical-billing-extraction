import app.config.settings  # noqa: F401
import asyncio
from app.worker.loop import run

if __name__ == "__main__":
    asyncio.run(run())
