import addict


class SpotifyResult(addict.Dict):
    def __iter__(self):
        if 'items' in self:
            return iter(self['items'])
        if 'seeds' in self:
            if 'tracks' in self:
                return iter(self['tracks'])
        return super().__iter__()

    def update(self, *args, **kwargs):
        if len(args) == 1 and 'items' in self:
            self['items'].extend(args[0])
        else:
            super().update(*args, **kwargs)
