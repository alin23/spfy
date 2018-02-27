import random
from urllib.parse import parse_qs, urlparse, urlunparse

import addict
from cached_property import cached_property

from . import limited_as_completed
from .. import config
from ..constants import API

LOCAL_ATTRIBUTES = {'_client', '_next_result', '_next_result_available', '_playable'}


class Playable:
    def __init__(self, result):
        self.result = result
        self.client = self.result._client

    async def play(self, device=None, index=None):
        return await self.result._put_with_params(
            dict(device_id=device, payload=self.get_data(index)), url=API.PLAY.value
        )

    def get_data(self, index=None):
        data = {}
        if 'tracks' in self.result or 'audio_features' in self.result:
            data['uris'] = list(map(self.client._get_track_uri, self.result))
            return data

        item = self.result[index] if index is not None else random.choice(self.result)
        if 'playlists' in self.result:
            data['context_uri'] = self.client._get_playlist_uri(item)
        elif 'artists' in self.result:
            data['context_uri'] = self.client._get_artist_uri(item)
        elif 'albums' in self.result:
            data['context_uri'] = self.client._get_album_uri(item)
        elif 'items' in self.result:
            data['context_uri'] = self.client._get_uri(item.type, item)
        elif self.result.type and self.result.type in {'album', 'artist', 'playlist'}:
            data['context_uri'] = self.client._get_uri(self.result.type, self.result)
        elif item.type == 'track':
            data['uris'] = list(map(self.client._get_track_uri, self.result))

        return data


# pylint: disable=too-few-public-methods
class SpotifyResultIterator:
    def __init__(self, result, limit=None):
        self.result = result
        self.limit = limit
        self.result_iterator = iter(result)
        self.params_list = self.result.get_next_params_list(limit)
        self.requests = (self.result._get_with_params(params) for params in self.params_list)
        self.responses = limited_as_completed(self.requests, config.http.concurrent_connections)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = next(self.result_iterator, None)
        if item is not None:
            return item

        self.result_iterator = iter(await self.responses.__anext__())  # pylint: disable=no-member
        return await self.__anext__()


class SpotifyResult(addict.Dict):
    ITER_KEYS = ('items', 'artists', 'tracks', 'albums', 'audio_features', 'playlists', 'devices')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_result = None
        self._playable = Playable(self)

    def __iter__(self):
        for key in self.ITER_KEYS:
            if key in self:
                if 'items' in self[key]:
                    return iter(self[key]['items'])
                return iter(self[key])
        return super().__iter__()

    def __getitem__(self, item):
        if isinstance(item, int):
            for key in self.ITER_KEYS:
                if key in self:
                    if 'items' in self[key]:
                        return iter(self[key]['items'][item])
                    return iter(self[key][item])
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

    async def play(self, device=None, index=None):
        return await self._playable.play(device, index)

    @cached_property
    def base_url(self):
        return urlunparse([*urlparse(self.href)[:3], '', '', ''])

    async def _get_with_params(self, params, url=None):
        return await self._client._get(url or self.base_url, **params)

    async def _put_with_params(self, params, url=None):
        return await self._client._put(url or self.base_url, **params)

    def get_next_params_list(self, limit=None):
        if self['next'] and self['href']:
            max_limit = limit or 50
            url = urlparse(self['href'])
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            limit = int(params.pop('limit', 20))
            offset = int(params.pop('offset', 0))
            return [{**params, 'limit': max_limit, 'offset': off} for off in range(offset + limit, self.total, max_limit)]
        return []

    async def all(self, limit=None):
        return [item async for item in self.iterall(limit)]  # pylint: disable=not-an-iterable

    async def next(self):
        if self._next_result:
            return self._next_result
        if self['next']:
            return await self._client._get(self['next'])
        return None

    def iterall(self, limit=None):
        return SpotifyResultIterator(self, limit)
