import os
import re
from enum import IntEnum
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
from datetime import date, datetime

from pony.orm import *

from .. import config

if os.getenv('DEBUG'):
    sql_debug(True)
    import logging
    logging.getLogger('pony.orm.sql').setLevel(logging.DEBUG)

db = Database()


class User(db.Entity):
    DEFAULT_EMAIL = 'spfy@backend'
    DEFAULT_USERNAME = 'spfy-backend'
    DEFAULT_USERID = uuid5(NAMESPACE_URL, DEFAULT_USERNAME)

    id = PrimaryKey(UUID, default=uuid4)
    email = Required(str, unique=True, index=True)
    username = Required(str, unique=True, index=True)
    token = Required(Json)
    api_calls = Required(int, default=0, volatile=True)
    created_at = Required(datetime, default=datetime.now)
    last_usage_at = Required(datetime, default=datetime.now)

    top_artists = Set('Artist')
    disliked_artists = Set('Artist')

    top_genres = Set('Genre')
    disliked_genres = Set('Genre')

    top_expires_at = Optional(date)

    def dislike(self, artist=None, genre=None):
        assert artist or genre
        if artist:
            self.disliked_artists.add(artist)
            self.top_artists.remove(artist)
        if genre:
            self.disliked_genres.add(genre)
            self.top_genres.remove(genre)

    @property
    def top_expired(self):
        return not self.top_expires_at or date.today() >= self.top_expires_at

    @classmethod
    def default(cls):
        try:
            return User[cls.DEFAULT_USERID]
        except ObjectNotFound:
            return User(id=cls.DEFAULT_USERID, username=cls.DEFAULT_USERNAME, email=cls.DEFAULT_EMAIL, token={})

    @staticmethod
    def token_updater(id):
        @db_session
        def update(token):
            User[id].token = token

        return update


class Image(db.Entity):
    url = PrimaryKey(str)
    height = Optional(int)
    width = Optional(int)
    playlist = Optional('Playlist')
    artist = Optional('Artist')


class SpotifyUser(db.Entity):
    id = PrimaryKey(str)
    name = Optional(str)
    playlists = Set('Playlist')

    @property
    def uri(self):
        return f'spotify:user:{self.id}'

    @property
    def href(self):
        return f'https://api.spotify.com/v1/users/{self.id}'

    @property
    def external_url(self):
        return f'http://open.spotify.com/user/{self.id}'


class Genre(db.Entity):
    name = PrimaryKey(str)
    artists = Set('Artist')
    playlists = Set('Playlist')
    fans = Set(User, reverse='top_genres', table='genre_fans')
    haters = Set(User, reverse='disliked_genres', table='genre_haters')


class Playlist(db.Entity):
    PARTICLE_RE = re.compile('The (?P<popularity>Sound|Pulse|Edge) of (?P<genre>.+)')
    SOUND_CITY_RE = re.compile('The Sound of (?P<city>.+) (?P<country_code>[A-Z]{2})')
    NEEDLE_RE = re.compile('The Needle / (?P<country>.+) (?P<date>[0-9]{8}) - (?P<popularity>Current|Emerging|Underground)')
    PINE_NEEDLE_RE = re.compile('The Pine Needle / (?P<country>.+)')

    class Popularity(IntEnum):
        SOUND = 0
        PULSE = 1
        EDGE = 2

        CURRENT = 3
        EMERGING = 4
        UNDERGROUND = 5

    id = PrimaryKey(str)
    collaborative = Required(bool)
    images = Set(Image, cascade_delete=True)
    name = Required(str)
    owner = Required(SpotifyUser)
    public = Required(bool)
    snapshot_id = Required(str)
    tracks = Required(int)
    popularity = Optional(int, index=True)
    genre = Optional(Genre)
    country = Optional(str, index=True)
    country_code = Optional(str, index=True, max_len=2)
    city = Optional(str, index=True)
    date = Optional(date)
    christmas = Optional(bool, index=True)
    composite_key(genre, popularity)

    @property
    def uri(self):
        return f'spotify:user:{self.owner.id}:playlist:{self.id}'

    @property
    def href(self):
        return f'https://api.spotify.com/v1/users/{self.owner.id}/playlists/{self.id}'

    @property
    def external_url(self):
        return f'http://open.spotify.com/user/{self.owner.id}/playlist/{self.id}'

    @classmethod
    def from_dict(cls, playlist):
        owner = (
            SpotifyUser.get(id=playlist.owner.id) or
            SpotifyUser(id=playlist.owner.id, name=playlist.owner.get('display_name', playlist.owner.id))
        )
        fields = {
            'id': playlist.id,
            'collaborative': playlist.collaborative,
            'name': playlist.name,
            'owner': owner,
            'public': playlist.public,
            'snapshot_id': playlist.snapshot_id,
            'tracks': playlist.tracks.total,
            'images': [Image.get(url=im.url) or Image(**im) for im in playlist.images]
        }

        match = cls.SOUND_CITY_RE.match(playlist.name)
        if match:
            city, country_code = match.groups()
            fields['popularity'] = cls.Popularity.SOUND.value
            fields['city'] = city.lower()
            fields['country_code'] = country_code
            return cls(**fields)

        match = cls.PARTICLE_RE.match(playlist.name)
        if match:
            popularity, genre = match.groups()
            genre = genre.lower()
            fields['popularity'] = cls.Popularity[popularity.upper()].value
            fields['genre'] = Genre.get(name=genre) or Genre(name=genre)
            fields['christmas'] = 'christmas' in genre
            return cls(**fields)

        match = cls.PINE_NEEDLE_RE.match(playlist.name)
        if match:
            country = match.groups()[0]
            fields['popularity'] = cls.Popularity.CURRENT.value
            fields['country'] = country.lower()
            fields['christmas'] = True
            return cls(**fields)

        match = cls.NEEDLE_RE.match(playlist.name)
        if match:
            country, date, popularity = match.groups()
            fields['popularity'] = cls.Popularity[popularity.upper()].value
            fields['country'] = country.lower()
            fields['date'] = datetime.strptime(date, '%Y%m%d').date()
            return cls(**fields)

        return cls(**fields)


class Artist(db.Entity):
    id = PrimaryKey(str)
    name = Required(str, index=True)
    followers = Required(int)
    genres = Set(Genre)
    images = Set(Image, cascade_delete=True)
    fans = Set(User, reverse='top_artists', table='artist_fans')
    haters = Set(User, reverse='disliked_artists', table='artist_haters')
    popularity = Optional(int)

    @property
    def uri(self):
        return f'spotify:artist:{self.id}'

    @property
    def href(self):
        return f'https://api.spotify.com/v1/artists/{self.id}'

    @property
    def external_url(self):
        return f'http://open.spotify.com/artist/{self.id}'

    @classmethod
    def from_dict(cls, artist):
        genres = [Genre.get(name=genre) or Genre(name=genre) for genre in artist.genres]
        images = [Image.get(url=image.url) or Image(**image) for image in artist.images]
        return cls(
            id=artist.id, name=artist.name, followers=artist.followers.total,
            genres=genres, images=images, popularity=artist.popularity)


if config.database.filename:
    config.database.filename = os.path.expandvars(config.database.filename)

db.bind(**config.database)
db.generate_mapping(create_tables=True)
