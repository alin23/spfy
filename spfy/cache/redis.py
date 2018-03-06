import asyncio
import aioredis
from .. import config, logger


async def go():
    pool = await aioredis.create_pool(**config.redis, loop=loop)
    await pool.execute('set', 'my-key', 'value')
    print(await pool.execute('get', 'my-key'))
    # graceful shutdown
    pool.close()
    await pool.wait_closed()
