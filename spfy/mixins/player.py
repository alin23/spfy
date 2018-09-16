import random
import sys
import threading
from collections import OrderedDict

from cached_property import cached_property
from first import first

from .. import config
from ..cache import Playlist, db_session
from ..constants import ItemType, TimeRange, VolumeBackend
from ..volume import (
    AlsaVolumeControl,
    ApplescriptVolumeControl,
    LinuxVolumeControl,
    SpotifyVolumeControl,
)


class PlayerMixin:
    def __init__(
        self,
        *args,
        device=None,
        alsa_device=None,
        alsa_mixer=None,
        speaker=None,
        **kwargs,
    ):
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
        return OrderedDict(
            {
                VolumeBackend.APPLESCRIPT: self._applescript_volume_control,
                VolumeBackend.LINUX: self._linux_volume_control,
                VolumeBackend.ALSA: self._alsa_volume_control,
                VolumeBackend.SPOTIFY: self._spotify_volume_control,
            }
        )

    @cached_property
    def _applescript_volume_control(self):
        try:
            # pylint: disable=no-member
            if sys.platform != "darwin":
                return None

            return ApplescriptVolumeControl(self.speaker)

        except:
            return None

    @cached_property
    def _linux_volume_control(self):
        try:
            # pylint: disable=no-member
            if sys.platform != "linux":
                return None

            return LinuxVolumeControl(
                self,
                self.alsa_mixer,
                spotify_device=self.device,
                alsa_device=self.alsa_device,
            )

        except:
            return None

    @cached_property
    def _alsa_volume_control(self):
        try:
            # pylint: disable=no-member
            if sys.platform != "linux":
                return None

            return AlsaVolumeControl(self.alsa_mixer, device=self.alsa_device)

        except:
            return None

    @cached_property
    def _spotify_volume_control(self):
        return SpotifyVolumeControl(self, device=self.device)

    def backend(self, backend=None, device=None):
        if not backend:
            return self._optimal_backend

        volume_backend = self._backends[VolumeBackend(backend)]
        if not volume_backend:
            raise ValueError(
                f"Backend {volume_backend} is not available on this system"
            )

        if (
            isinstance(volume_backend, SpotifyVolumeControl)
            and device
            and device != self.device
        ):
            volume_backend = SpotifyVolumeControl(self, device=device)
        return volume_backend

    def change_volume(self, by=0, to=None, backend=None, device=None):
        volume_backend = self.backend(backend, device=device)
        if to is not None:
            volume = to
        else:
            volume = volume_backend.volume
        volume_backend.volume = volume + by
        return volume

    def volume_up(self, backend=None):
        return self.change_volume(by=+1, backend=backend)

    def volume_down(self, backend=None):
        return self.change_volume(by=-1, backend=backend)

    def fade_up(self, **kwargs):
        self.fade(**{**config.volume.fade.up, **kwargs})

    def fade_down(self, **kwargs):
        self.fade(**{**config.volume.fade.down, **kwargs})

    #  pylint: disable=too-many-arguments

    def fade(
        self,
        limit=50,
        start=0,
        step=1,
        seconds=300,
        force=False,
        backend=None,
        spotify_volume=100,
        device=None,
    ):
        volume_backend = self.backend(backend, device=device)
        if not isinstance(volume_backend, SpotifyVolumeControl):
            self.change_volume(
                to=spotify_volume, backend=VolumeBackend.SPOTIFY, device=device
            )
        self.change_volume(to=start, backend=backend, device=device)
        kwargs = dict(
            limit=int(limit),
            start=int(start),
            step=int(step),
            seconds=int(seconds),
            force=bool(force),
        )
        threading.Thread(target=volume_backend.fade, kwargs=kwargs).start()

    @db_session
    def play_recommended_tracks(
        self, time_range=TimeRange.LONG_TERM, device=None, **kwargs
    ):
        fade_args = kwargs.get("fade_args") or {
            k[5:]: v for k, v in kwargs.items() if k.startswith("fade_")
        }
        recommendation_args = kwargs.get("recommendation_args") or {
            k[4:]: v for k, v in kwargs.items() if k.startswith("rec_")
        }
        recommendation_args["time_range"] = time_range
        tracks = self.recommend_by_top_artists(**recommendation_args)
        self.fade_up(device=device, **fade_args)
        result = self.start_playback(tracks=tracks, device=device)
        return {"playing": True, "device": device, "tracks": tracks, "result": result}

    @db_session
    def play_recommended_genre(
        self, time_range=TimeRange.LONG_TERM, device=None, **kwargs
    ):
        fade_args = kwargs.get("fade_args") or {
            k[5:]: v for k, v in kwargs.items() if k.startswith("fade_")
        }
        popularity = random.choice(list(Playlist.Popularity)[:3])
        genre = (
            self.top_genres(time_range=time_range)
            .select()
            .without_distinct()
            .random(1)[0]
        )
        playlist = self.genre_playlist(genre.name, popularity)
        while not playlist:
            playlist = self.genre_playlist(genre.name, popularity)
        self.fade_up(device=device, **fade_args)
        result = playlist.play(self, device=device)
        return {
            "playing": True,
            "device": device,
            "playlist": playlist.to_dict(),
            "result": result,
        }

    @db_session
    def play(
        self, time_range=TimeRange.LONG_TERM, device=None, item_type=None, **kwargs
    ):
        item_type = item_type or random.choice([ItemType.TRACKS, ItemType.PLAYLIST])
        if item_type == ItemType.TRACKS:
            return self.play_recommended_tracks(time_range, device, **kwargs)

        if item_type == ItemType.PLAYLIST:
            return self.play_recommended_genre(time_range, device, **kwargs)

        return {"playing": False}
