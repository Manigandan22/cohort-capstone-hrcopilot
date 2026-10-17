"""Exit 0 if the employees table is empty (so start.sh should seed), 1 otherwise."""

import asyncio
import sys

from sqlalchemy import text

from app.db.session import engine


async def main() -> int:
    async with engine.connect() as conn:
        count = (await conn.execute(text("SELECT COUNT(*) FROM employees"))).scalar_one()
    await engine.dispose()
    return 0 if count == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
