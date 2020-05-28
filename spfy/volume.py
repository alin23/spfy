# -*- coding: utf-8 -*-
import abc
import asyncio
import subprocess
from time import sleep

from . import logger
from .constants import VOLUME_FADE_SECONDS

try:
    import alsaaudio  # pylint: disable=import-error
except:
    pass


def cap(volume, _min=1, _max=100):
    return min(max(volume, _min), _max)


class VolumeControl(abc.ABC):
    @abc.abstractmethod
    def unmute(self):
        pass

    @abc.abstractmethod
    def mute(self):
        pass

    @abc.abstractproperty
    def volume(self):  # pylint: disable=method-hidden
        pass

    @volume.setter
    def volume(self, val):
        pass

    @abc.abstractmethod
    def should_stop_fading(self, device_volume, old_volume, step):
        return abs(device_volume - old_volume) > (step + 2)

    def fade(
        self, limit=100, start=1, step=1, seconds=VOLUME_FADE_SECONDS, force=False
    ):
        try:
            self.unmute()
            delay = seconds / ((limit - start) / step)
            device_volume = self.volume
            self.volume = start
            for next_volume in range(start + step, limit + 1, step):
                sleep(delay)
                device_volume = self.volume
                old_volume = next_volume - step
                if not force and self.should_stop_fading(
                    device_volume, old_volume, step
                ):
                    logger.debug(
                        """A stop fading condition was met:
                        Current volume: %s
                        Old volume: %s""",
                        device_volume,
                        old_volume,
                    )
                    break

                logger.debug("Setting volume to %s", next_volume)
                self.volume = next_volume
        except Exception as exc:
            logger.exception(exc)


class SpotifyVolumeControl(VolumeControl):
    def __init__(self, client, device=None):
        self.spotify = client
        self.device = device
        self.old_volume = None

    def mute(self):
        self.old_volume = self.volume
        self.spotify.volume(0, device=self.device)

    def unmute(self):
        if self.old_volume:
            self.volume = self.old_volume
        else:
            self.volume = 1

    def should_stop_fading(self, device_volume, old_volume, step):
        is_playing = self.spotify.current_playback().is_playing
        logger.debug("Spotify playing: %s", is_playing)
        return (
            super().should_stop_fading(device_volume, old_volume, step)
            or not is_playing
        )

    @property
    def volume(self):
        return int(self.spotify.get_device(device=self.device).volume_percent or 0) + 1

    @volume.setter
    def volume(self, val):
        self.spotify.volume(cap(val), device=self.device)


class SpotifyVolumeControlAsync(VolumeControl):
    def __init__(self, client, device=None):
        self.spotify = client
        self.device = device
        self.old_volume = None

    async def mute(self):
        self.old_volume = await self.volume()
        await self.spotify.volume(0, device=self.device)

    async def unmute(self):
        if self.old_volume:
            await self.set_volume(self.old_volume)
        else:
            await self.set_volume(1)

    async def is_playing(self):
        playback = await self.spotify.current_playback()
        return playback and playback.is_playing

    async def should_stop_fading(self, device_volume, old_volume, step):
        is_playing = await self.is_playing()
        logger.debug("Spotify playing: %s", is_playing)
        return (
            super().should_stop_fading(device_volume, old_volume, step)
            or not is_playing
        )

    async def volume(self):  # pylint: disable=method-hidden
        device = await self.spotify.get_device(device=self.device)
        return int(device.volume_percent or 0)

    async def set_volume(self, val, fade=False, fade_seconds=5):
        vol = cap(val)
        if not fade:
            await self.spotify.volume(vol, device=self.device)
        else:
            current_volume = await self.volume()
            step = -1 if vol < current_volume else 1
            await self.fade(
                limit=vol, start=current_volume + step, step=step, seconds=fade_seconds
            )
        return vol

    async def force_fade(self, limit, step, delay):
        def fade_done(vol):
            if step > 0:
                return vol >= limit
            return vol <= limit

        device_volume = await self.volume()
        while not fade_done(device_volume) and (await self.is_playing()):
            next_volume = device_volume + step
            logger.debug("Setting volume to %s", next_volume)
            await self.set_volume(next_volume)
            await asyncio.sleep(delay)
            device_volume = await self.volume()

    async def fade(
        self, limit=100, start=1, step=1, seconds=VOLUME_FADE_SECONDS, force=False
    ):
        limit = cap(limit)
        delay = seconds / ((limit - start) / step)
        await self.set_volume(start)

        if force:
            await self.force_fade(limit, step, delay)
        else:
            device_volume = await self.volume()
            for next_volume in range(start + step, limit + step, step):
                await asyncio.sleep(delay)
                device_volume = await self.volume()
                old_volume = next_volume - step
                should_stop_fading = await self.should_stop_fading(
                    device_volume, old_volume, step
                )
                if should_stop_fading:
                    logger.debug(
                        """A stop fading condition was met:
                        Current volume: %s
                        Old volume: %s""",
                        device_volume,
                        old_volume,
                    )
                    break

                logger.debug("Setting volume to %s", next_volume)
                await self.set_volume(next_volume)

        device_volume = await self.volume()
        if device_volume <= abs(step):
            await self.spotify.pause_playback()


class AlsaVolumeControl(VolumeControl):
    def __init__(self, mixer_name, device=None):
        if isinstance(device, str):
            kwargs = dict(device=device)
        elif isinstance(device, int):
            kwargs = dict(cardindex=device)
        else:
            kwargs = dict()
        self.mixer_name = mixer_name
        self.device = device
        self.mixer = alsaaudio.Mixer(mixer_name, **kwargs)

    def mute(self):
        self.mixer.setmute(1)

    def unmute(self):
        self.mixer.setmute(0)

    def should_stop_fading(self, device_volume, old_volume, step):
        is_mute = self.mixer.getmute()[0]
        logger.debug("Mute status: %s", is_mute)
        return super().should_stop_fading(device_volume, old_volume, step) or is_mute

    @property
    def volume(self):
        vol = self.mixer.getvolume()
        return sum(vol) // len(vol)

    @volume.setter
    def volume(self, val):
        self.mixer.setvolume(max(val, 1))


class ApplescriptVolumeControl(VolumeControl):
    def __init__(self, device=None):
        self.device = device
        self.old_volume = None

    def fade(
        self, limit=100, start=1, step=1, seconds=VOLUME_FADE_SECONDS, force=False
    ):
        if self.device:
            self.switch_audio_device(self.device)
        super().fade(limit, start, step, seconds, force)

    @staticmethod
    def osascript(cmd):
        cmd = f"/usr/bin/osascript -e '{cmd}'"
        result = subprocess.check_output(cmd, shell=True).decode().strip()
        logger.debug("Command: %s", cmd)
        logger.debug("Output: %s", result)
        return result

    @staticmethod
    def switch_audio_device(device):
        logger.debug("Switching audio device: %s", device)
        subprocess.call(f'/usr/local/bin/SwitchAudioSource -s "{device}"', shell=True)

    def should_stop_fading(self, device_volume, old_volume, step):
        is_playing = (
            self.osascript('tell application "Spotify" to get player state')
            == "playing"
        )
        logger.debug("Spotify playing: %s", is_playing)
        return (
            super().should_stop_fading(device_volume, old_volume, step)
            or not is_playing
        )

    def spotify_mute(self):
        self.old_volume = self.spotify_volume
        self.osascript('tell application "Spotify" to set sound volume to 0')

    def spotify_unmute(self):
        if self.old_volume:
            self.spotify_volume = self.old_volume
        else:
            self.spotify_volume = 1

    def mute(self):
        self.osascript("set volume with output muted")

    def unmute(self):
        self.osascript("set volume without output muted")

    @property
    def spotify_volume(self):
        return int(self.osascript('tell application "Spotify" to get sound volume')) + 1

    @spotify_volume.setter
    def spotify_volume(self, val):
        self.osascript(
            f'tell application "Spotify" to set sound volume to {max(val, 1)}'
        )

    @property
    def system_volume(self):
        return int(self.osascript("output volume of (get volume settings)"))

    @system_volume.setter
    def system_volume(self, val):
        self.osascript(f"set volume output volume {max(val, 1)}")

    @property
    def volume(self):
        return self.system_volume

    @volume.setter
    def volume(self, val):
        self.old_volume = self.volume
        self.system_volume = val
        self.spotify_volume = val // 2


class LinuxVolumeControl(AlsaVolumeControl):
    def __init__(
        self, spotify_client, alsa_mixer_name, spotify_device=None, alsa_device=None
    ):
        super().__init__(alsa_mixer_name, device=alsa_device)
        self.spotify_volume_control = SpotifyVolumeControl(
            spotify_client, spotify_device
        )

    def should_stop_fading(self, device_volume, old_volume, step):
        return super().should_stop_fading(
            device_volume, old_volume, step
        ) or self.spotify_should_stop_fading(device_volume, old_volume, step)

    def spotify_should_stop_fading(self, device_volume, old_volume, step):
        return self.spotify_volume_control.should_stop_fading(
            device_volume, old_volume, step
        )


class LinuxVolumeControlAsync(AlsaVolumeControl):
    def __init__(
        self, spotify_client, alsa_mixer_name, spotify_device=None, alsa_device=None
    ):
        super().__init__(alsa_mixer_name, device=alsa_device)
        self.spotify_volume_control = SpotifyVolumeControlAsync(
            spotify_client, spotify_device
        )

    async def should_stop_fading(self, device_volume, old_volume, step):
        return super().should_stop_fading(
            device_volume, old_volume, step
        ) or await self.spotify_should_stop_fading(device_volume, old_volume, step)

    async def spotify_should_stop_fading(self, device_volume, old_volume, step):
        return await self.spotify_volume_control.should_stop_fading(
            device_volume, old_volume, step
        )

    async def fade(
        self, limit=100, start=1, step=1, seconds=VOLUME_FADE_SECONDS, force=False
    ):
        try:
            self.unmute()
            delay = seconds / ((limit - start) / step)
            device_volume = self.volume
            self.volume = start
            for next_volume in range(start + step, limit + 1, step):
                sleep(delay)
                device_volume = self.volume
                old_volume = next_volume - step
                should_stop_fading = await self.should_stop_fading(
                    device_volume, old_volume, step
                )
                if not force and should_stop_fading:
                    logger.debug(
                        """A stop fading condition was met:
                        Current volume: %s
                        Old volume: %s""",
                        device_volume,
                        old_volume,
                    )
                    break

                logger.debug("Setting volume to %s", next_volume)
                self.volume = next_volume
        except Exception as exc:
            logger.exception(exc)
