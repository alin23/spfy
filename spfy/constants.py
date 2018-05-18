import re
from enum import Enum

from .frange import frange


class ItemType(Enum):
    TRACKS = "tracks"
    TRACK = "track"
    PLAYLIST = "playlist"
    ARTIST = "artist"
    ALBUM = "album"


class TimeRange(Enum):
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"


class VolumeBackend(Enum):
    SPOTIFY = "spotify"
    APPLESCRIPT = "applescript"
    ALSA = "alsa"
    LINUX = "linux"


class AuthFlow(Enum):
    AUTHORIZATION_CODE = "authorization_code"
    CLIENT_CREDENTIALS = "client_credentials"


class AudioFeature(Enum):
    ACOUSTICNESS = "acousticness"
    DANCEABILITY = "danceability"
    DURATION_MS = "duration_ms"
    ENERGY = "energy"
    INSTRUMENTALNESS = "instrumentalness"
    KEY = "key"
    LIVENESS = "liveness"
    LOUDNESS = "loudness"
    MODE = "mode"
    POPULARITY = "popularity"
    SPEECHINESS = "speechiness"
    TEMPO = "tempo"
    TIME_SIGNATURE = "time_signature"
    VALENCE = "valence"


class AudioFeatureRange(Enum):
    ACOUSTICNESS = frange(0.0, 1.01, 0.01)
    DANCEABILITY = frange(0.0, 1.01, 0.01)
    DURATION_MS = range((30 * 60 * 1000) + 1)
    ENERGY = frange(0.0, 1.01, 0.01)
    INSTRUMENTALNESS = frange(0.0, 1.01, 0.01)
    KEY = range(0, 12)
    LIVENESS = frange(0.0, 1.01, 0.01)
    LOUDNESS = frange(-60.0, 0.1, 0.1)
    MODE = range(2)
    POPULARITY = range(101)
    SPEECHINESS = frange(0.0, 1.01, 0.01)
    TEMPO = range(321)
    TIME_SIGNATURE = range(9)
    VALENCE = frange(0.0, 1.01, 0.01)


class Scope(Enum):
    PLAYLIST_READ_PRIVATE = "playlist-read-private"
    PLAYLIST_READ_COLLABORATIVE = "playlist-read-collaborative"
    PLAYLIST_MODIFY_PUBLIC = "playlist-modify-public"
    PLAYLIST_MODIFY_PRIVATE = "playlist-modify-private"
    STREAMING = "streaming"
    UGC_IMAGE_UPLOAD = "ugc-image-upload"
    USER_FOLLOW_MODIFY = "user-follow-modify"
    USER_FOLLOW_READ = "user-follow-read"
    USER_LIBRARY_READ = "user-library-read"
    USER_LIBRARY_MODIFY = "user-library-modify"
    USER_READ_PRIVATE = "user-read-private"
    USER_READ_BIRTHDATE = "user-read-birthdate"
    USER_READ_EMAIL = "user-read-email"
    USER_TOP_READ = "user-top-read"
    USER_READ_PLAYBACK_STATE = "user-read-playback-state"
    USER_MODIFY_PLAYBACK_STATE = "user-modify-playback-state"
    USER_READ_CURRENTLY_PLAYING = "user-read-currently-playing"
    USER_READ_RECENTLY_PLAYED = "user-read-recently-played"


AllScopes = [scope.value for scope in Scope]


class API(Enum):
    PREFIX = "https://api.spotify.com"
    ALBUM = "/v1/albums/{id}"
    ALBUM_TRACKS = "/v1/albums/{id}/tracks"
    ALBUMS = "/v1/albums"
    ARTIST = "/v1/artists/{id}"
    ARTIST_ALBUMS = "/v1/artists/{id}/albums"
    ARTIST_RELATED_ARTISTS = "/v1/artists/{id}/related-artists"
    ARTIST_TOP_TRACKS = "/v1/artists/{id}/top-tracks"
    ARTISTS = "/v1/artists"
    AUDIO_ANALYSIS = "/v1/audio-analysis/{id}"
    AUDIO_FEATURES_SINGLE = "/v1/audio-features/{id}"
    AUDIO_FEATURES_MULTIPLE = "/v1/audio-features"
    RECOMMENDATIONS = "/v1/recommendations"
    RECOMMENDATIONS_GENRES = "/v1/recommendations/available-genre-seeds"
    AUTHORIZE = "https://accounts.spotify.com/authorize"
    TOKEN = "https://accounts.spotify.com/api/token"
    CATEGORIES = "/v1/browse/categories"
    CATEGORY = "/v1/browse/categories/{id}"
    CATEGORY_PLAYLISTS = "/v1/browse/categories/{id}/playlists"
    FEATURED_PLAYLISTS = "/v1/browse/featured-playlists"
    NEW_RELEASES = "/v1/browse/new-releases"
    ME = "/v1/me"
    MY_ALBUMS = "/v1/me/albums"
    MY_ALBUMS_CONTAINS = "/v1/me/albums/contains"
    MY_FOLLOWING = "/v1/me/following"
    MY_FOLLOWING_CONTAINS = "/v1/me/following/contains"
    MY_PLAYLISTS = "/v1/me/playlists"
    MY_TOP = "/v1/me/top/{type}"
    MY_TRACKS = "/v1/me/tracks"
    MY_TRACKS_CONTAINS = "/v1/me/tracks/contains"
    PLAYLIST = "/v1/users/{user_id}/playlists/{playlist_id}"
    PLAYLISTS = "/v1/users/{user_id}/playlists"
    PLAYLIST_FOLLOWERS = "/v1/users/{owner_id}/playlists/{playlist_id}/followers"
    PLAYLIST_FOLLOWERS_CONTAINS = (
        "/v1/users/{user_id}/playlists/{playlist_id}/followers/contains"
    )
    PLAYLIST_IMAGES = "/v1/users/{user_id}/playlists/{playlist_id}/images"
    PLAYLIST_TRACKS = "/v1/users/{user_id}/playlists/{playlist_id}/tracks"
    SEARCH_ALBUM = "/v1/search?type=album"
    SEARCH_ARTIST = "/v1/search?type=artist"
    SEARCH_PLAYLIST = "/v1/search?type=playlist"
    SEARCH_TRACK = "/v1/search?type=track"
    TRACK = "/v1/tracks/{id}"
    TRACKS = "/v1/tracks"
    USER = "/v1/users/{user_id}"
    CURRENTLY_PLAYING = "/v1/me/player/currently-playing"
    DEVICES = "/v1/me/player/devices"
    NEXT = "/v1/me/player/next"
    PAUSE = "/v1/me/player/pause"
    PLAY = "/v1/me/player/play"
    PLAYER = "/v1/me/player"
    PREVIOUS = "/v1/me/player/previous"
    RECENTLY_PLAYED = "/v1/me/player/recently-played"
    REPEAT = "/v1/me/player/repeat"
    SEEK = "/v1/me/player/seek"
    SHUFFLE = "/v1/me/player/shuffle"
    VOLUME = "/v1/me/player/volume"


VOLUME_FADE_SECONDS = 5 * 60
DEVICE_ID_RE = re.compile(r"[a-zA-Z0-9]{40}")
PLAYLIST_URI_RE = re.compile(r"spotify:user:[^:]+:playlist:[^:]+")
