# -*- coding: utf-8 -*-

import abc
import subprocess
from time import sleep

from . import logger
from .constants import VOLUME_FADE_SECONDS

try:
    import alsaaudio
except:
    pass


class VolumeControl(abc.ABC):
    @abc.abstractmethod
    def unmute(self):
        pass

    @abc.abstractmethod
    def mute(self):
        pass

    @abc.abstractproperty
    def volume(self):
        pass

    @volume.setter
    def volume(self, val):
        pass

    @abc.abstractmethod
    def should_stop_fading(self, device_volume, old_volume):
        return abs(device_volume - old_volume) > 2

    def fade(self, limit=100, start=1, step=1, seconds=VOLUME_FADE_SECONDS, force=False):
        self.unmute()

        delay = seconds / ((limit - start) / step)
        device_volume = self.volume

        self.volume = start

        for next_volume in range(start + step, limit + 1, step):
            sleep(delay)
            device_volume = self.volume
            old_volume = next_volume - step

            if not force and self.should_stop_fading(device_volume, old_volume):
                logger.debug(f'''A stop fading condition was met:
                    Current volume: {device_volume}
                    Old volume: {old_volume}''')
                break

            logger.debug(f'Setting volume to {next_volume}')
            self.volume = next_volume


class SpotifyVolumeControl(VolumeControl):
    def __init__(self, client, device=None):
        self.spotify = client
        self.device = device
        self.old_volume = None

    def mute(self):
        self.old_volume = self.volume
        self.spotify.volume(0, device_id=self.device)

    def unmute(self):
        if self.old_volume:
            self.volume = self.old_volume
        else:
            self.volume = 1

    def should_stop_fading(self, device_volume, old_volume):
        is_playing = self.spotify.current_playback().is_playing
        logger.debug(f'Spotify playing: {is_playing}')
        return (
            super().should_stop_fading(device_volume, old_volume) or
            not is_playing)

    @property
    def volume(self):
        return int(self.spotify.get_device(device=self.device).volume_percent) + 1

    @volume.setter
    def volume(self, val):
        self.spotify.volume(max(val, 1), device_id=self.device)


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

    def should_stop_fading(self, device_volume, old_volume):
        is_mute = self.mixer.getmute()[0]
        logger.debug(f'Mute status: {is_mute}')
        return (
            super().should_stop_fading(device_volume, old_volume) or
            is_mute)

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

    def fade(self, limit=100, start=1, step=1, seconds=VOLUME_FADE_SECONDS, force=False):
        if self.device:
            self.switch_audio_device(self.device)

        super().fade(limit, start, step, seconds, force)

    def osascript(self, cmd):
        cmd = f"/usr/bin/osascript -e '{cmd}'"
        result = subprocess.check_output(cmd, shell=True).decode().strip()

        logger.debug('Command: %s', cmd)
        logger.debug('Output: %s', result)

        return result

    def switch_audio_device(self, device):
        logger.debug(f'Switching audio device: {device}')
        subprocess.call(f"/usr/local/bin/SwitchAudioSource -s \"{device}\"", shell=True)

    def should_stop_fading(self, device_volume, old_volume):
        is_playing = self.osascript('tell application "Spotify" to get player state') == 'playing'
        logger.debug(f'Spotify playing: {is_playing}')
        return (
            super().should_stop_fading(device_volume, old_volume) or
            not is_playing)

    def spotify_mute(self):
        self.old_volume = self.spotify_volume
        self.osascript('tell application "Spotify" to set sound volume to 0')

    def spotify_unmute(self):
        if self.old_volume:
            self.spotify_volume = self.old_volume
        else:
            self.spotify_volume = 1

    def mute(self):
        self.osascript('set volume with output muted')

    def unmute(self):
        self.osascript('set volume without output muted')

    @property
    def spotify_volume(self):
        return int(self.osascript('tell application "Spotify" to get sound volume')) + 1

    @spotify_volume.setter
    def spotify_volume(self, val):
        self.osascript(f'tell application "Spotify" to set sound volume to {max(val, 1)}')

    @property
    def system_volume(self):
        return int(self.osascript('output volume of (get volume settings)'))

    @system_volume.setter
    def system_volume(self, val):
        self.osascript(f'set volume output volume {max(val, 1)}')

    @property
    def volume(self):
        return self.system_volume

    @volume.setter
    def volume(self, val):
        self.old_volume = self.volume
        self.system_volume = val
        self.spotify_volume = val // 2


class LinuxVolumeControl(AlsaVolumeControl):
    def __init__(self, spotify_client, alsa_mixer_name, spotify_device=None, alsa_device=None):
        super().__init__(alsa_mixer_name, device=alsa_device)
        self.spotify_volume_control = SpotifyVolumeControl(spotify_client, spotify_device)

    def should_stop_fading(self, device_volume, old_volume):
        return (
            super().should_stop_fading(device_volume, old_volume) or
            self.spotify_volume_control.should_stop_fading(device_volume, old_volume))

    def get_amixer_cmd(self, volume):
        cmd = ['/usr/bin/amixer']
        if self.device:
            flag = '-c' if isinstance(self.device, int) else '-D'
            cmd += [flag, self.device]

        cmd += ['sset', self.mixer_name, 'unmute', f'{volume}%']

        logger.debug(cmd)

        return cmd

    def fade(self, limit=100, start=1, step=1, seconds=VOLUME_FADE_SECONDS, force=False):
        subprocess.call(self.get_amixer_cmd(start))

        super().fade(limit, start, step, seconds, force)
