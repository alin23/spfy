from .. import *  # isort:skip

# pylint: disable=wrong-import-order
import asyncio
from itertools import islice


class LimitedAsCompletedError(Exception):
    def __init__(self, *args, original_exc=None, remaining_futures=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_exc = original_exc
        self.remaining_futures = remaining_futures


def should_ignore_exception(exc, ignore_exceptions):
    return ignore_exceptions is True or (
        isinstance(ignore_exceptions, (tuple, Exception))
        and isinstance(exc, ignore_exceptions)
    )


async def limited_as_completed(coros, limit, ignore_exceptions=False):
    """
    Run the coroutines (or futures) supplied in the
    iterable coros, ensuring that there are at most
    limit coroutines running at any time.
    Return an iterator whose values, when waited for,
    are Future instances containing the results of
    the coroutines.
    Results may be provided in any order, as they
    become available.
    """
    futures = [asyncio.ensure_future(c) for c in islice(coros, 0, limit)]

    async def first_to_finish(ignore_exceptions=False):
        while True:
            await asyncio.sleep(0)
            for f in futures:
                if f.done():
                    futures.remove(f)
                    try:
                        newf = next(coros)
                        futures.append(asyncio.ensure_future(newf))
                    except StopIteration:
                        pass
                    try:
                        return f.result()
                    except Exception as exc:
                        if should_ignore_exception(exc, ignore_exceptions):
                            logger.warning("Ignoring exception:")
                            logger.exception(exc)
                            return None
                        raise LimitedAsCompletedError(
                            *exc.args, original_exc=exc, remaining_futures=futures
                        )

    while futures:
        yield await first_to_finish(ignore_exceptions=ignore_exceptions)


from .client import SpotifyClient  # isort:skip
from .result import SpotifyResult  # isort:skip
from .wrapper import Spotify  # isort:skip
