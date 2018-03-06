import os
import random
import asyncio
from functools import partial
from collections import OrderedDict

from first import first
from cached_property import cached_property

from ... import config
from ...cache import Playlist, db_session
from ...volume import (
    AlsaVolumeControl,
    LinuxVolumeControl,
    ApplescriptVolumeControl,
    SpotifyVolumeControlAsync
)
from ...constants import ItemType, TimeRange, VolumeBackend


class PlayerMixin:
    def __init__(self, *args, device=None, alsa_device=None, alsa_mixer=None, speaker=None, **kwargs):
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
                return None
        except:
            return None

        return ApplescriptVolumeControl(self.speaker)

    @cached_property
    def _linux_volume_control(self):
        try:
            if os.uname().sysname != 'Linux':
                return None
        except:
            return None

        return LinuxVolumeControl(
            self, self.alsa_mixer, spotify_device=self.device, alsa_device=self.alsa_device, _async=True
        )

    @cached_property
    def _alsa_volume_control(self):
        try:
            if os.uname().sysname != 'Linux':
                return None
        except:
            return None

        return AlsaVolumeControl(self.alsa_mixer, device=self.alsa_device)

    @cached_property
    def _spotify_volume_control(self):
        return SpotifyVolumeControlAsync(self, device=self.device)

    def backend(self, backend=None, device=None):
        if not backend:
            return self._optimal_backend

        volume_backend = self._backends[VolumeBackend(backend)]
        if not volume_backend:
            raise ValueError(f'Backend {volume_backend} is not available on this system')
        if isinstance(volume_backend, SpotifyVolumeControlAsync) and device and device != self.device:
            volume_backend = SpotifyVolumeControlAsync(self, device=device)

        return volume_backend

    async def change_volume(self, value=0, backend=None, device=None):
        volume_backend = self.backend(backend, device=device)
        if isinstance(volume_backend, SpotifyVolumeControlAsync):
            volume = await volume_backend.volume()
            await volume_backend.set_volume(volume + value)
        else:
            volume = volume_backend.volume + value
            volume_backend.volume = volume
        return volume

    async def volume_up(self, backend=None):
        return await self.change_volume(value=+1, backend=backend)

    async def volume_down(self, backend=None):
        return await self.change_volume(value=-1, backend=backend)

    async def fade_up(self, **kwargs):
        await self.fade(**{**config.volume.fade.up, **kwargs})

    async def fade_down(self, **kwargs):
        await self.fade(**{**config.volume.fade.down, **kwargs})

    #  pylint: disable=too-many-arguments
    async def fade(
        self,
        limit=50,
        start=0,
        step=1,
        seconds=300,
        force=False,
        backend=None,
        spotify_volume=100,
        device=None,
        blocking=False
    ):
        volume_backend = self.backend(backend, device=device)
        if not isinstance(volume_backend, SpotifyVolumeControlAsync):
            await self.change_volume(spotify_volume, backend=VolumeBackend.SPOTIFY, device=device)

        await self.change_volume(start, backend=backend, device=device)
        kwargs = dict(limit=int(limit), start=int(start), step=int(step), seconds=int(seconds), force=bool(force))

        loop = asyncio.get_event_loop()
        if isinstance(volume_backend, SpotifyVolumeControlAsync):
            task = loop.create_task(volume_backend.fade(**kwargs))
            if blocking:
                await task
            else:
                return task
        else:
            loop.run_in_executor(partial(volume_backend.fade, **kwargs))

        return None

    @db_session
    async def play_recommended_tracks(self, time_range=TimeRange.LONG_TERM, device=None, **kwargs):
        fade_args = kwargs.get('fade_args') or {k[5:]: v for k, v in kwargs.items() if k.startswith('fade_')}
        recommendation_args = kwargs.get('recommendation_args') or {
            k[4:]: v
            for k, v in kwargs.items()
            if k.startswith('rec_')
        }
        recommendation_args['time_range'] = time_range

        tracks = await self.recommend_by_top_artists(**recommendation_args)

        await self.fade_up(device=device, **fade_args)
        result = await self.start_playback(tracks=tracks, device=device)
        return {'playing': True, 'device': device, 'tracks': tracks, 'result': result}

    @db_session
    async def play_recommended_genre(self, time_range=TimeRange.LONG_TERM, device=None, **kwargs):
        fade_args = kwargs.get('fade_args') or {k[5:]: v for k, v in kwargs.items() if k.startswith('fade_')}

        popularity = random.choice(list(Playlist.Popularity)[:3])
        top_genres = await self.top_genres(time_range=time_range)
        genre = top_genres.select().without_distinct().random(1)[0]

        playlist = self.genre_playlist(genre.name, popularity)
        while not playlist:
            playlist = self.genre_playlist(genre.name, popularity)

        await self.fade_up(device=device, **fade_args)
        result = await playlist.play(self, device=device)
        return {'playing': True, 'device': device, 'playlist': playlist.to_dict(), 'result': result}

    @db_session
    async def play(self, time_range=TimeRange.LONG_TERM, device=None, item_type=None, **kwargs):
        item_type = item_type or random.choice([ItemType.TRACKS, ItemType.PLAYLIST])
        if item_type == ItemType.TRACKS:
            return await self.play_recommended_tracks(time_range, device, **kwargs)
        if item_type == ItemType.PLAYLIST:
            return await self.play_recommended_genre(time_range, device, **kwargs)
        return {'playing': False}
