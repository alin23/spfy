import os
import re
import time
import random
from enum import IntEnum
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
from datetime import date, datetime

import psycopg2.extras
# pylint: disable=unused-import
from pony.orm import (
    Set,
    Json,
    Database,
    Optional,
    Required,
    PrimaryKey,
    ObjectNotFound,
    get,
    desc,
    select,
    ormtypes,
    sql_debug,
    db_session,
    composite_key
)
from psycopg2.extensions import register_adapter

from .. import Unsplash, config
from ..constants import TimeRange

register_adapter(ormtypes.TrackedDict, psycopg2.extras.Json)

if os.getenv('SQL_DEBUG'):
    sql_debug(True)
    import logging
    logging.getLogger('pony.orm.sql').setLevel(logging.DEBUG)

db = Database()


class User(db.Entity):
    _table_ = 'users'

    DEFAULT_EMAIL = 'spfy@backend'
    DEFAULT_USERNAME = 'spfy-backend'
    DEFAULT_USERID = uuid5(NAMESPACE_URL, DEFAULT_USERNAME)

    id = PrimaryKey(UUID, default=uuid4)  # pylint: disable=redefined-builtin
    email = Required(str, unique=True, index=True)
    username = Required(str, unique=True, index=True)
    token = Required(Json, volatile=True)
    api_calls = Required(int, default=0, volatile=True)
    created_at = Required(datetime, default=datetime.now)
    last_usage_at = Required(datetime, default=datetime.now)

    top_artists = Set('Artist')
    disliked_artists = Set('Artist')

    top_genres = Set('Genre')
    disliked_genres = Set('Genre')

    top_expires_at = Optional(Json, volatile=True)

    def dislike(self, artist=None, genre=None):
        assert artist or genre
        if artist:
            self.disliked_artists.add(artist)
            self.top_artists.remove(artist)
        if genre:
            self.disliked_genres.add(genre)
            self.top_genres.remove(genre)
            self.disliked_artists.add(genre.artists)
            self.top_artists.remove(genre.artists)

    def top_expired(self, time_range):
        time_range = TimeRange(time_range).value
        return (
            not self.top_expires_at or time_range not in self.top_expires_at
            or time.time() >= self.top_expires_at[time_range]
        )

    @classmethod
    def default(cls):
        try:
            return User[cls.DEFAULT_USERID]
        except ObjectNotFound:
            return User(id=cls.DEFAULT_USERID, username=cls.DEFAULT_USERNAME, email=cls.DEFAULT_EMAIL, token={})

    @staticmethod
    def token_updater(_id):
        @db_session
        def update(token):
            User[_id].token = token

        return update


class Image(db.Entity):
    _table_ = 'images'

    REGULAR = 1080
    SMALL = 400
    THUMB = 200

    url = PrimaryKey(str)
    height = Optional(int)
    width = Optional(int)
    color = Optional(str)
    playlist = Optional('Playlist')
    artist = Optional('Artist')
    genre = Optional('Genre')
    unsplash_user_fullname = Optional(str)
    unsplash_user_username = Optional(str)

    # pylint: disable=no-self-use
    def unsplash_url(self):
        return f'https://unsplash.com/?utm_source={config.unsplash.app_name}&utm_medium=referral'

    def unsplash_user_url(self):
        return f'https://unsplash.com/@{self.unsplash_user_username}?utm_source={config.unsplash.app_name}&utm_medium=referral'

    def unsplash_credits(self):
        return {
            'user_name': self.unsplash_user_fullname,
            'user_url': self.unsplash_user_url(),
            'site_url': self.unsplash_url()
        }


class SpotifyUser(db.Entity):
    _table_ = 'spotify_users'

    id = PrimaryKey(str)  # pylint: disable=redefined-builtin
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
    _table_ = 'genres'

    name = PrimaryKey(str)
    images = Set(Image)
    artists = Set('Artist')
    playlists = Set('Playlist')
    fans = Set(User, reverse='top_genres', table='genre_fans')
    haters = Set(User, reverse='disliked_genres', table='genre_haters')

    def play(self, client, device=None):
        popularity = random.choice(list(Playlist.Popularity)[:3])
        playlist = client.genre_playlist(self.name, popularity)
        return playlist.play(device=device)

    def image(self, width=None, height=None):
        if width:
            image = self.images.select().where(lambda i: i.width >= width).order_by(Image.width).first()
        elif height:
            image = self.images.select().where(lambda i: i.height >= height).order_by(Image.height).first()
        else:
            image = self.images.select().order_by(desc(Image.width)).first()

        return image

    def get_image_queries(self):
        words = self.name.split()
        stems = [[w[:i] for i in range(len(w), 2, -1)] for w in words]
        return [*words, self.name, *sum(stems, [])]

    async def fetch_image(self, width=None, height=None):
        image = self.image(width, height)
        if image:
            return image

        queries = self.get_image_queries()
        photo = None
        for query in queries:
            photos = await Unsplash.photo.random(query=query, orientation='squarish')
            if photos:
                photo = photos[0]
                break
        else:
            photo = await Unsplash.photo.random(query=query, orientation='squarish')[0]

        if photo is None:
            return None

        ratio = photo.height / photo.width
        params = {
            'genre': self,
            'color': photo.color,
            'unsplash_user_fullname': photo.user.name,
            'unsplash_user_username': photo.user.username,
        }
        Image(url=photo.urls.full, width=photo.width, height=photo.height, **params)
        Image(url=photo.urls.regular, width=Image.REGULAR, height=int(round(ratio * Image.REGULAR)), **params)
        Image(url=photo.urls.small, width=Image.SMALL, height=int(round(ratio * Image.SMALL)), **params)
        Image(url=photo.urls.thumb, width=Image.THUMB, height=int(round(ratio * Image.THUMB)), **params)
        return self.image(width, height)


class Playlist(db.Entity):
    _table_ = 'playlists'

    PARTICLE_RE = re.compile('The (?P<popularity>Sound|Pulse|Edge) of (?P<genre>.+)')
    SOUND_CITY_RE = re.compile('The Sound of (?P<city>.+) (?P<country_code>[A-Z]{2})')
    NEEDLE_RE = re.compile(
        'The Needle / (?P<country>.+) (?P<date>[0-9]{8}) - (?P<popularity>Current|Emerging|Underground)'
    )
    PINE_NEEDLE_RE = re.compile('The Pine Needle / (?P<country>.+)')

    class Popularity(IntEnum):
        SOUND = 0
        PULSE = 1
        EDGE = 2

        CURRENT = 3
        EMERGING = 4
        UNDERGROUND = 5

    id = PrimaryKey(str)  # pylint: disable=redefined-builtin
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

    def play(self, client, device=None):
        return client.start_playback(playlist=self.uri, device=device)

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
            SpotifyUser.get(id=playlist.owner.id)
            or SpotifyUser(id=playlist.owner.id, name=playlist.owner.get('display_name', playlist.owner.id))
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
            country, _date, popularity = match.groups()
            fields['popularity'] = cls.Popularity[popularity.upper()].value
            fields['country'] = country.lower()
            fields['date'] = datetime.strptime(_date, '%Y%m%d').date()
            return cls(**fields)

        return cls(**fields)


class Artist(db.Entity):
    _table_ = 'artists'

    id = PrimaryKey(str)  # pylint: disable=redefined-builtin
    name = Required(str, index=True)
    followers = Required(int)
    genres = Set(Genre)
    images = Set(Image, cascade_delete=True)
    fans = Set(User, reverse='top_artists', table='artist_fans')
    haters = Set(User, reverse='disliked_artists', table='artist_haters')
    popularity = Optional(int)

    def play(self, client, device=None):
        return client.start_playback(artist=self.uri, device=device)

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
            id=artist.id,
            name=artist.name,
            followers=artist.followers.total,
            genres=genres,
            images=images,
            popularity=artist.popularity
        )


if config.database.filename:
    config.database.filename = os.path.expandvars(config.database.filename)

db.bind(**config.database)
db.generate_mapping(create_tables=True)
