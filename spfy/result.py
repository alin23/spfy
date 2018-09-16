import random
import threading
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from urllib.parse import parse_qs, urlparse, urlunparse

import addict
from cached_property import cached_property

from . import config
from .constants import API

LOCAL_ATTRIBUTES = {"_client", "_next_result", "_next_result_available", "_playable"}


class Playable:
    def __init__(self, result):
        self.result = result
        self.client = self.result._client

    def play(self, device=None, index=None):
        return self.result._put_with_params(
            dict(device_id=device, payload=self.get_data(index)), url=API.PLAY.value
        )

    def get_data(self, index=None):
        data = {}
        if "tracks" in self.result or "audio_features" in self.result:
            data["uris"] = list(map(self.client._get_track_uri, self.result))
            return data

        item = self.result[index] if index is not None else random.choice(self.result)
        if "playlists" in self.result:
            data["context_uri"] = self.client._get_playlist_uri(item)
        elif "artists" in self.result:
            data["context_uri"] = self.client._get_artist_uri(item)
        elif "albums" in self.result:
            data["context_uri"] = self.client._get_album_uri(item)
        elif "items" in self.result:
            data["context_uri"] = self.client._get_uri(item.type, item)
        elif self.result.type and self.result.type in {"album", "artist", "playlist"}:
            data["context_uri"] = self.client._get_uri(self.result.type, self.result)
        elif item.type == "track":
            data["uris"] = list(map(self.client._get_track_uri, self.result))
        return data


class SpotifyResult(addict.Dict):
    ITER_KEYS = (
        "items",
        "artists",
        "tracks",
        "albums",
        "audio_features",
        "playlists",
        "devices",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_result_available = threading.Event()
        self._next_result = None
        self._playable = Playable(self)

    def __iter__(self):
        for key in self.ITER_KEYS:
            if key in self:
                if "items" in self[key]:
                    return iter(self[key]["items"])

                return iter(self[key])

        return super().__iter__()

    def __getitem__(self, item):
        if isinstance(item, int):
            for key in self.ITER_KEYS:
                if key in self:
                    if "items" in self[key]:
                        return iter(self[key]["items"][item])

                    return iter(self[key][item])

        return super().__getitem__(item)

    @classmethod
    def _hook(cls, item):
        if isinstance(item, dict):
            return addict.Dict(item)

        if isinstance(item, (list, tuple)):
            return type(item)(cls._hook(elem) for elem in item)

        return item

    def items(self):
        return filter(lambda i: i[0] not in LOCAL_ATTRIBUTES, super().items())

    def keys(self):
        return super().keys() - LOCAL_ATTRIBUTES

    def values(self):
        return [v for k, v in self.items()]

    def play(self, device=None, index=None):
        return self._playable.play(device, index)

    @cached_property
    def base_url(self):
        return urlunparse([*urlparse(self.href)[:3], "", "", ""])

    def _get_with_params(self, params, url=None):
        return self._client._get(url or self.base_url, **params)

    def _put_with_params(self, params, url=None):
        return self._client._put(url or self.base_url, **params)

    def get_next_params_list(self, limit=None):
        if self["next"] and self["href"]:
            max_limit = limit or 50
            url = urlparse(self["href"])
            params = {k: v[0] for k, v in parse_qs(url.query).items()}
            limit = int(params.pop("limit", 20))
            offset = int(params.pop("offset", 0))
            return [
                {**params, "limit": max_limit, "offset": off}
                for off in range(offset + limit, self.total, max_limit)
            ]

        return []

    def all(self, limit=None):
        params_list = self.get_next_params_list(limit)
        if not params_list:
            return []

        with ThreadPoolExecutor(
            max_workers=config.http.parallel_connections
        ) as executor:
            return chain.from_iterable(
                executor.map(
                    self._get_with_params, params_list, timeout=10 * len(params_list)
                )
            )

    @cached_property
    def next(self):
        if self["next"]:
            return self._client._get(self["next"])

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
