import os
import random
import threading
from collections import OrderedDict

from first import first
from cached_property import cached_property

from .. import config
from ..cache import Playlist, db_session
from ..volume import (
    AlsaVolumeControl,
    LinuxVolumeControl,
    SpotifyVolumeControl,
    ApplescriptVolumeControl
)
from ..constants import ItemType, TimeRange, VolumeBackend


class PlayerMixin:
    def __init__(self, device=None, alsa_device=None, alsa_mixer=None, speaker=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device = device or config.player.device
        self.alsa_device = alsa_device or config.player.alsa.device
        self.alsa_mixer = alsa_mixer or config.player.alsa.mixer
        self.speaker = speaker or config.player.speaker

    @cached_property
    def _optimal_backend(self):
        return first(self._backends.values())

    @cached_property
    def _backends(self):
        return OrderedDict({
            VolumeBackend.APPLESCRIPT: self._applescript_volume_control,
            VolumeBackend.LINUX: self._linux_volume_control,
            VolumeBackend.ALSA: self._alsa_volume_control,
            VolumeBackend.SPOTIFY: self._spotify_volume_control
        })

    @cached_property
    def _applescript_volume_control(self):
        try:
            if os.uname().sysname != 'Darwin':
                return
        except:
            return

        return ApplescriptVolumeControl(self.speaker)

    @cached_property
    def _linux_volume_control(self):
        try:
            if os.uname().sysname != 'Linux':
                return
        except:
            return

        return LinuxVolumeControl(self, self.alsa_mixer, spotify_device=self.device, alsa_device=self.alsa_device)

    @cached_property
    def _alsa_volume_control(self):
        try:
            if os.uname().sysname != 'Linux':
                return
        except:
            return

        return AlsaVolumeControl(self.alsa_mixer, device=self.alsa_device)

    @cached_property
    def _spotify_volume_control(self):
        return SpotifyVolumeControl(self, device=self.device)

    def backend(self, backend=None):
        if not backend:
            return self._optimal_backend

        volume_backend = self._backends[VolumeBackend(backend)]
        if not volume_backend:
            raise ValueError(f'Backend {volume_backend} is not available on this system')

        return volume_backend

    def change_volume(self, value=0, backend=None):
        volume_backend = self.backend(backend)
        volume = volume_backend.volume + value
        volume_backend.volume = volume
        return volume

    def volume_up(self, backend=None):
        return self.change_volume(value=+1, backend=backend)

    def volume_down(self, backend=None):
        return self.change_volume(value=-1, backend=backend)

    def fade_up(self, **kwargs):
        self.fade(**{**config.volume.fade.up, **kwargs})

    def fade_down(self, **kwargs):
        self.fade(**{**config.volume.fade.down, **kwargs})

    def fade(self, limit=50, start=0, step=1, seconds=300, force=False, backend=None, spotify_volume=100):
        volume_backend = self.backend(backend)
        if not isinstance(volume_backend, SpotifyVolumeControl):
            self.change_volume(spotify_volume, VolumeBackend.SPOTIFY)

        volume_backend.volume = start
        kwargs = dict(limit=limit, start=start, step=step, seconds=seconds, force=force)
        threading.Thread(target=volume_backend.fade, kwargs=kwargs).start()

    @db_session
    def play_recommended_tracks(self, time_range=TimeRange.LONG_TERM, device=None, **kwargs):
        fade_args = kwargs.get('fade_args') or {k[5:]: v for k, v in kwargs.items() if k.startswith('fade_')}
        recommendation_args = kwargs.get('recommendation_args') or {k[4:]: v for k, v in kwargs.items() if k.startswith('rec_')}
        recommendation_args['time_range'] = time_range

        tracks = self.recommend_by_top_artists(**recommendation_args)
        self.fade_up(**fade_args)
        result = self.start_playback(tracks=tracks, device=device)
        return {'playing': True, 'device': device, 'tracks': tracks, 'result': result}

    @db_session
    def play_recommended_genre(self, time_range=TimeRange.LONG_TERM, device=None, **kwargs):
        fade_args = kwargs.get('fade_args') or {k[5:]: v for k, v in kwargs.items() if k.startswith('fade_')}

        popularity = random.choice(list(Playlist.Popularity)[:3])
        genre = self.top_genres().select().without_distinct().random(1)[0]

        playlist = self.genre_playlist(genre.name, popularity)
        while not playlist:
            playlist = self.genre_playlist(genre.name, popularity)
        self.fade_up(**fade_args)
        result = playlist.play(self, device=device)
        return {'playing': True, 'device': device, 'playlist': playlist.to_dict(), 'result': result}

    @db_session
    def play(self, time_range=TimeRange.LONG_TERM, device=None, **kwargs):
        item_type = random.choice([ItemType.TRACKS, ItemType.PLAYLIST])
        if item_type == ItemType.TRACKS:
            return self.play_recommended_tracks(time_range, device, **kwargs)
        elif item_type == ItemType.PLAYLIST:
            return self.play_recommended_genre(time_range, device, **kwargs)
        return {'playing': False}
