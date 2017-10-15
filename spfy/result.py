import addict
from cached_property import cached_property


class SpotifyResult(addict.Dict):
    ITER_KEYS = ('items', 'artists', 'tracks', 'albums', 'audio_features')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __iter__(self):
        for key in self.ITER_KEYS:
            if key in self:
                return iter(self[key])
        return super().__iter__()

    @cached_property
    def all(self):
        return [item for item in self.iterall()]

    @cached_property
    def next(self):
        if self['next']:
            return self.client._get(self['next'])
        else:
            return None

    def iterall(self):
        result = self

        while result:
            for item in result:
                yield item
            result = result.next
