import threading
from itertools import chain
from urllib.parse import parse_qs, urlparse, urlunparse
from concurrent.futures import ThreadPoolExecutor

import addict
from cached_property import cached_property

from . import config

LOCAL_ATTRIBUTES = {'_client', '_next_result', '_next_result_available'}


class SpotifyResult(addict.Dict):
    ITER_KEYS = ('items', 'artists', 'tracks', 'albums', 'audio_features')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_result_available = threading.Event()
        self._next_result = None

    def __iter__(self):
        for key in self.ITER_KEYS:
            if key in self:
                return iter(self[key])
        return super().__iter__()

    def __getitem__(self, item):
        if isinstance(item, int):
            for key in self.ITER_KEYS:
                if key in self:
                    return self[key][item]
        return super().__getitem__(item)

    @classmethod
    def _hook(cls, item):
        if isinstance(item, dict):
            return addict.Dict(item)
        elif isinstance(item, (list, tuple)):
            return type(item)(cls._hook(elem) for elem in item)
        return item

    def items(self):
        return filter(lambda i: i[0] not in LOCAL_ATTRIBUTES, super().items())

    def keys(self):
        return super().keys() - LOCAL_ATTRIBUTES

    def values(self):
        return [v for k, v in self.items()]

    @cached_property
    def base_url(self):
        return urlunparse([*urlparse(self.href)[:3], '', '', ''])

    def _get_with_params(self, params):
        return self._client._get(self.base_url, **params)

    def get_next_params_list(self):
        if self['next'] and self['href']:
            url = urlparse(self['href'])
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            limit = int(params.pop('limit', 20))
            offset = int(params.pop('offset', 0))
            return [
                {**params, 'limit': 50, 'offset': off}
                for off in range(offset + limit, self.total, 50)]
        else:
            return []

    def all(self):
        params_list = self.get_next_params_list()
        if not params_list:
            return []

        with ThreadPoolExecutor(max_workers=config.http.concurrent_connections) as executor:
            return chain.from_iterable(executor.map(self._get_with_params, params_list, timeout=10 * len(params_list)))

    @cached_property
    def next(self):
        if self['next']:
            return self._client._get(self['next'])
        else:
            return None

    def _fetch_next_result(self, result):
        self._next_result = result.next
        self._next_result_available.set()

    def iterall(self):
        result = self

        while result:
            threading.Thread(target=self._fetch_next_result, args=(result,)).start()
            for item in result:
                yield item

            if self._next_result_available.wait(10):
                result = self._next_result
                self._next_result_available.clear()
            else:
                break
