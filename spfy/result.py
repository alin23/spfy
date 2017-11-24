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

    def to_dict(self):
        base = {}
        for key, value in self.items():
            if isinstance(value, type(self)):
                base[key] = value.to_dict()
            elif isinstance(value, (list, tuple)):
                base[key] = type(value)(
                    item.to_dict() if isinstance(item, type(self)) else
                    item for item in value)
            elif self.client and isinstance(value, self.client.__class__):
                continue
            else:
                base[key] = value
        return base

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
