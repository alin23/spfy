import addict


class SpotifyResult(addict.Dict):
    def __iter__(self):
        if 'items' in self:
            return iter(self['items'])
        if 'seeds' in self:
            if 'tracks' in self:
                return iter(self['tracks'])
        return super().__iter__()
