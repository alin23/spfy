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
MANELISTI = {
    "2Ieszafc1unlRGyRmhGDFB",
    "2JoWWy2bVRC2bcx67BwILT",
    "2pepyBw5kRmhDaFkK0hiRQ",
    "2ZLpHjgeA6bEDlEVHhOOXL",
    "55xJmWjZC4Pa3FwEsMY28w",
    "3qf1tO2qoPVryMXg02WKRh",
    "3VnLLHKFN1ZB38FoJC9UEx",
    "6byfmUAqPBLK0owbuFEXlF",
    "3gnne9V6R0jmzs4ksnjNdy",
    "6Ujb9g9pljLl91qELsPZYo",
    "7aTSDkvSajML4o7CLlynwK",
    "0z0oRip2G1bkbX4spG9BpC",
    "2ekMCPMFstPliouB6rrGJK",
    "7unGBhZ0rI9iM76JLRFUCT",
    "1GXLkfzd7QjC8XIn4Dz1vp",
    "0gV4T1KXkmkrgTwQ7opgAN",
    "1I6I9IA5b9Q0H7JAmd19n8",
    "2L8Uf1Doaz8iJK1QKwh1I4",
    "3nEGbFFQiHXnjhbJVwzega",
    "1f2Y1i56FYEzsiRdrAYjsq",
    "06f5XN8rUFdabqdXn1Xuqg",
    "0TWTJophavu8mv6OF8st9q",
    "67zjnbtDq97ewfnbCq6oXw",
    "36Pv4nrbKXaEZHJinKrGDx",
    "2jjbkZe4cW2DJHTVZ3TVws",
    "5kqGOZA4rJho5gHdDTX5aZ",
    "0g5DbVhyQh959B7Z2ZYdPp",
    "1i6II3AaDfzer4QeNFuXne",
    "3Bu7CGd7oH8Ckitp0EsyZ5",
    "2SBpyLN4PD8DcPWlKeA4K8",
    "7gDHM1wBJAZOr69gU2o9oo",
    "4EocdGKc8KuWvNY8it8yBC",
    "4f9wGjBz9mNYQDuxP6KL56",
    "13zongmqs6nw7IB8qJUoyC",
    "7vEj3NqOilkYqgfbLCM2PT",
    "00kgsXttY3ZuxxXC6rUrZe",
    "10CpGdX2tyq1vGgf2JZaHL",
    "0xjHfnYTyL2yhSSdHpttsq",
    "18Z7SMNytEkKaiixfOX50w",
    "1Lbh8dcDjsa3BcE9LWyXyD",
    "0y7yHqqTeiK9xw4JRoTEHG",
    "2TrnHdJsXpzfxMFIZViwdI",
    "0nqyHPKioCjZ91eUcQ24SB",
    "3s5gg1dJCw5igSIo2DSVmQ",
    "3Mpgf08uPOZUYMnFDRSRV8",
    "5TZfuTwYa8JJga6TQ66vCG",
    "3LxWFtPzHcmzMO3k4rFUf7",
    "7noZM8YzX3rCq0uHcAuBXh",
    "7LLJvMSmGCDzaFKzGJVJ1V",
    "0fIp0Ar4hS7kBJjlv0dbEs",
    "7jSeLyH6h7qlWMaczER5Cd",
    "7iwW4N99bE6IqmetoSwJ7h",
    "1RNezj0YMlyMErtT86iWwg",
    "3VPPqsKpzzAFfY0f4qeaMy",
    "4Dk2VpQboT3GZ48989H9Sg",
    "3BPyexYwvn1oac4pCumPv8",
    "12bZ3FVNkc52pKG4YSgbSu",
    "7hyaaCD9Ydxt0dRJZaL4wt",
    "4EO93NpDQGwrdlzlQfnDCW",
    "6nU9Rg6157nS2p7zUfZJ6p",
    "2D0PmICj8cPJCN2KwdaFda",
    "0vXdmVC1505NYuTDouJo6G",
    "0fvOPoGXlSHNkGT2O0ATB7",
    "13Uivonlj8WicABhVkLyzl",
    "1WgCdu3YOI6rVp6Hr4NSc2",
    "3D18mEm1VBL6UMjklDeKvr",
    "5r9KPAzF16iwXfh0t15796",
    "0CisGgglR3QoT8r9LwaNNK",
    "3aBSSgGns3zM1UlXLuSWpL",
    "3nZ1cE2XuL2GaZ5VENV70S",
    "3FxwMafw6ORSgJgcm1BaaR",
    "2wtyDAPYMH93u49gBfVYPx",
    "7jct42t9M1sP3Mh83LX2mE",
    "4pp9qALPcnQmVpibuDyrQJ",
    "3ou1VcyERvmAyF1R7XIGmn",
    "4ouqMiepI4OQyd72R59pMQ",
    "7bQDLDdhEHr1ytwmKqTqgA",
    "0ksMyhTvlPBVBxpefKlxMC",
    "6ixTSq8mQsI26zrlUBTLS4",
    "6nvH1YG6WAFxGIEtX3JpzZ",
    "3axETwb6iK7HozXqv4bzqq",
    "2bqKyDcBvcWSbmKwhgF6Lq",
    "36tFKRhXaFBlycxiOvJVbs",
    "5KneFAP1oboQ4HpupQ2Y8m",
    "2KlIfHQACY0wbZt9TzKywN",
    "1lhvoeeajvhGmW4JEZ5nJv",
    "7BssMhtelPJEK1qycRG3iA",
    "2phUIFr6Q7b2ifSc4wJTOF",
    "1P9DU63Z7cYemiEjjeQmFs",
    "3Mpgf08uPOZUYMnFDRSRV8",
    "5tc4sgBPwnW8MfIceXu7VB",
    "39QykPFzm2emgtN9XyCJmV",
    "6I45uNgBW2URvWbQKqU5HY",
    "52OT0kDJk0eHbGJoXVXoID",
    "3MOeFK0Be57Mi1x5oLCfuL",
    "5VjP62EoivYMUpx5i6O55W",
    "4uNuwIueJrsSRtAXgRzDmb",
    "416ojj5IWmW6UJOrBDo931",
    "3Ols0qSo3Jy6JXsuzpFvIw",
    "0bEgGdcKWtP80aFtWTN5du",
    "3LMJ8PwGKLVgQiXNaTjzfD",
    "4sbgJi3VL7O1vS381MsLKn",
    "4RS1TcSqxr45eMFQe5wxdn",
    "1SGx0Rio4xIMWvgOLU4h3E",
    "4KBDKBcZsrqI7omC9s1KlG",
    "1ghEvzFzgDEpXsJTikumGw",
    "1zA7dHMrodgGqEN8owgAe3",
    "2EzZEVmCMtOSJtC8i1WeOQ",
    "09CTGylU0khFHdw7fMjyWg",
    "1pmqhKz2NUq8FEiX00brLu",
    "0j1HQ4RWuFbJPx2LnIITmH",
    "4tAxFVQ9LN2qVEi41ilqdE",
    "6XuwlE6QNkhGKauGl4jM7t",
    "034IOMKjllnYpbg9gqmavp",
    "14Hi4xJIidPV5v3RqEGLKV",
    "4ttfBkWrRYxGvHb9jcN9SF",
    "4KKWPAUUkcouh7xKjhLyLt",
    "3JI7vQAX2z1B0PxX01JJRp",
    "3Bq7FLSOaiIikbW6dawZNR",
    "4WwEX3orWGm7Fu0GyHTZBP",
    "6BqA8d5VxPy4nrk0TrKJNf",
    "0WYeg1DLQThOv5edYVaAeF",
    "1RbiY7VrOLuxuxTgGuUznZ",
    "79E5wmHfOMwxy4WCh4mDIL",
    "3BIuTXBzsorpOEIZVhwTss",
    "7sdwE7oJbhmsjjYeDYUQ3P",
    "2tqwGlXSGYYuZvBjF4wpuj",
    "0LRizmzjNKAjWlmkYBJi8V",
    "52fwrx4YWimHFpHqQCcLBb",
    "7KL6Xmrib9qHpU1xD9gRPB",
    "0EIBqLeqCKubCI2ZYYQDRw",
    "7c3NeCsxUjVOGVqaMOMmVP",
    "2KLd63rASWHMFH1jDp6Uoz",
    "4hlkJZ5XzNFKqxBgP0D7GB",
    "4ZknxfV6pMMTWCESLnra6X",
    "78Dw4QMPizHHRjcJSvgnYB",
    "4egN2mVCQGfz9NUuMBIjkg",
    "100vi1IPH5Go3Pb2UM3BWp",
    "6rESRpDyAmxiU41eboLcIR",
    "6JHsPCTCGVnvwEdsqdDgK6",
    "7xl58ylWDt598otFvFNFB0",
    "1HXo00S8hutdzcPZmhchLP",
    "5GxeTUY8mjqd8HczZqj2aI",
}
