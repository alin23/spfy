import functools
from collections import OrderedDict

from .db import *


def async_lru(maxsize=100):
    cache = OrderedDict()

    def decorator(fn):
        @functools.wraps(fn)
        async def memoizer(*args, **kwargs):
            key = str((args, kwargs))
            try:
                cache[key] = cache.pop(key)
            except KeyError:
                if len(cache) >= maxsize:
                    cache.popitem(last=False)
                cache[key] = await fn(*args, **kwargs)
            return cache[key]

        return memoizer

    return decorator
