# coding: utf-8
import os
import json
import socket
import pathlib
import threading
from time import sleep
from hashlib import sha256
from operator import attrgetter
from functools import partialmethod

import hug
import backoff
import sendgrid
from first import first
from oauthlib.oauth2 import WebApplicationClient, BackendApplicationClient
from requests_oauthlib import OAuth2Session
from sendgrid.helpers.mail import (
    Mail,
    Email,
    Content,
    Substitution,
    Personalization
)
from wsgiref.simple_server import make_server
from oauthlib.oauth2.rfc6749.errors import TokenExpiredError

from .log import get_logger
from .util import SpotifyResult
from .constants import API, AuthFlow, TimeRange, AudioFeature
from .exceptions import (
    SpotifyException,
    SpotifyForbiddenException,
    SpotifyRateLimitException,
    SpotifyCredentialsException,
    SendGridCredentialsException
)

logger = get_logger()
retry_after = None


def expo():
    global retry_after
    for delay in backoff.expo():
        if retry_after:
            yield retry_after
            retry_after = None
        else:
            yield delay


class SpotifyClient:
    def __init__(self, token=None, username=None, email=None, cache_path=None,
                 proxies=None, requests_timeout=None, flow=AuthFlow.CLIENT_CREDENTIALS,
                 scope=None, client_id=None, client_secret=None, redirect_uri=None, port=None):
        '''
        Create a Spotify API object.

        :param token: An authorization token
        :param username: Spotify username
        :param email: Spotify email
        :param cache_path: Token cache file path
        :param proxies: Definition of proxies
        :param requests_timeout: Tell Requests to stop waiting for a response after a given number of seconds
        :param oauth: Authenticate using authorization code flow
        :param scope: Scope to use when authenticating
        :param client_id: Spotify Application Client ID
        :param client_secret: Spotify Application Client Secret
        :param redirect_uri: Spotify Application Redirect URI
        :param port: Callback listening port
        '''
        self.scope = scope
        self.email = email
        self.username = username
        self.cache_path = self._get_cache_path(cache_path, email, username)

        self.client_id = client_id or os.getenv('SPOTIFY_CLIENT_ID')
        self.client_secret = client_secret or os.getenv('SPOTIFY_CLIENT_SECRET')
        self.redirect_uri = self._get_redirect_uri(redirect_uri, port)
        self.port = port

        self.flow = flow
        self.oauth_session = self._get_session(flow)
        self.proxies = proxies
        self.requests_timeout = requests_timeout
        self._token = token

    def _get_redirect_uri(self, redirect_uri, port):
        redirect_uri = (
            redirect_uri or
            os.getenv('SPOTIFY_REDIRECT_URI') or
            f'http://{socket.gethostname()}.local')

        if port and redirect_uri:
            redirect_uri += f':{port}'

        return redirect_uri

    def _get_cache_path(self, cache_path=None, email=None, username=None):
        if cache_path:
            cache_path = pathlib.Path(cache_path)
        else:
            token_hash = sha256((email or username or 'spotify-backend').encode('utf-8')).hexdigest()
            cache_path = pathlib.Path.home().joinpath(".cache-" + token_hash)

        return cache_path

    def _get_session(self, flow):
        if flow == AuthFlow.AUTHORIZATION_CODE:
            oauth_session = OAuth2Session(
                self.client_id, redirect_uri=self.redirect_uri, scope=self.scope,
                auto_refresh_url=API.TOKEN.value, token_updater=self.cache_token)
        elif flow == AuthFlow.CLIENT_CREDENTIALS:
            oauth_session = OAuth2Session(client=BackendApplicationClient(self.client_id))

        return oauth_session

    def get_cached_token(self):
        token = None
        if self.cache_path.exists():
            content = self.cache_path.read_text()
            if content:
                try:
                    token = json.loads(content)
                except:
                    pass

        return token

    def authenticate(self, force=False):
        if not (self.client_id and self.client_secret):
            raise SpotifyCredentialsException

        if force:
            token = {}

        if not force:
            token = self.get_cached_token()
            if token:
                self.oauth_session.token = token
                self._token = token
                return self._token

        if isinstance(self.oauth_session._client, BackendApplicationClient):
            self._token = self.oauth_session.fetch_token(
                token_url=API.TOKEN.value,
                client_id=self.client_id,
                client_secret=self.client_secret)
            self.cache_token(self._token)
            return self._token

        if isinstance(self.oauth_session._client, WebApplicationClient):
            client = self

            @hug.get('/')
            def callback(code: hug.types.text, state: hug.types.text):
                try:
                    client._token = client.oauth_session.fetch_token(
                        token_url=API.TOKEN.value,
                        client_id=client.client_id,
                        client_secret=client.client_secret,
                        code=code, state=state)
                    return 'Successfully logged in!'
                except:
                    return 'Could not get authorization token.'

            api = __hug__.http.server(None)  # noqa
            httpd = make_server('', self.port, api)

            threading.Thread(target=httpd.serve_forever, daemon=True).start()

            authorization_url, _ = self.oauth_session.authorization_url(API.AUTHORIZE.value)
            if self.email:
                self.send_auth_email(self.email, authorization_url)
            else:
                logger.info(f'Login here: {authorization_url}')

            self._token = {}
            logger.info('Waiting for authorization code...')
            while not self._token:
                sleep(0.5)
            else:
                httpd.shutdown()
                self.cache_token(self._token)
                return self._token

    def cache_token(self, token):
        self.cache_path.write_text(json.dumps(token))

    def send_auth_email(self, email, auth_url, fallback=True):
        api_key = os.getenv('SENDGRID_API_KEY')
        sender = os.getenv('SENDGRID_SENDER')
        template_id = os.getenv('SENDGRID_TEMPLATE_ID')

        if not (api_key and sender):
            if fallback:
                logger.info(f'Login here: {auth_url}')
            else:
                raise SendGridCredentialsException

        sg = sendgrid.SendGridAPIClient(apikey=api_key)

        mail = Mail()
        mail.from_email = Email(sender)
        mail.subject = "Spotify Connect"
        pers = Personalization()
        pers.add_to(Email(email))
        mail.add_personalization(pers)
        if template_id:
            mail.template_id = template_id
            pers.add_substitution(Substitution('%auth_url%', auth_url))
        else:
            login_html = pathlib.Path(__file__).with_name('login.html')
            html_content = login_html.read_text().format(auth_url=auth_url)
            content = Content('text/html', html_content)
            mail.add_content(content)

        sg.client.mail.send.post(request_body=mail.get())

    def _check_response(self, response):
        global retry_after
        try:
            response.raise_for_status()
        except:
            if response.status_code == 429 or (response.status_code >= 500 and response.status_code < 600):
                retry_after = int(response.headers.get('Retry-After', 0))
                raise SpotifyRateLimitException(response)
            elif response.status_code == 403:
                self.authenticate(force=True)
                raise SpotifyForbiddenException(response)
            else:
                raise SpotifyException(response)

    @backoff.on_exception(expo, (TokenExpiredError, SpotifyRateLimitException, SpotifyForbiddenException))
    def _internal_call(self, method, url, payload, params):
        if not self._token:
            self.authenticate()

        if not url.startswith('http'):
            url = API.PREFIX.value + url

        logger.debug(url)
        try:
            r = self.oauth_session.request(
                method, url,
                proxies=self.proxies,
                timeout=self.requests_timeout,
                headers={'Content-Type': 'application/json'},
                data=json.dumps(payload),
                params={k: v for k, v in params.items() if v is not None},
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        except TokenExpiredError:
            self.authenticate(force=True)
            raise

        logger.debug('HTTP Status Code: {r.status_code}')
        logger.debug(f'{method}: {r.url}')
        if payload:
            logger.debug(f'DATA: {json.dumps(payload)}')

        try:
            self._check_response(r)
        finally:
            r.connection.close()

        if r.text and len(r.text) > 0 and r.text != 'null':
            results = r.json()
            logger.debug(f'RESP: {results}')
            return SpotifyResult(results)
        else:
            return None

    def _get(self, url, args=None, payload=None, **kwargs):
        if args:
            kwargs.update(args)
        return self._internal_call('GET', url, payload, kwargs)

    def _post(self, url, args=None, payload=None, **kwargs):
        if args:
            kwargs.update(args)
        return self._internal_call('POST', url, payload, kwargs)

    def _delete(self, url, args=None, payload=None, **kwargs):
        if args:
            kwargs.update(args)
        return self._internal_call('DELETE', url, payload, kwargs)

    def _put(self, url, args=None, payload=None, **kwargs):
        if args:
            kwargs.update(args)
        return self._internal_call('PUT', url, payload, kwargs)

    def all_results(self, result):
        next_result = self.next(result)
        while next_result:
            result.update(next_result)
            next_result = self.next(next_result)

        return result

    def next(self, result):
        ''' returns the next result given a paged result

            Parameters:
                - result - a previously returned paged result
        '''
        if result['next']:
            return self._get(result['next'])
        else:
            return None

    def previous(self, result):
        ''' returns the previous result given a paged result

            Parameters:
                - result - a previously returned paged result
        '''
        if result['previous']:
            return self._get(result['previous'])
        else:
            return None

    def track(self, track_id):
        ''' returns a single track given the track's ID, URI or URL

            Parameters:
                - track_id - a spotify URI, URL or ID
        '''

        id = self._get_track_id(track_id)
        return self._get(API.TRACK.value.format(id=id))

    def tracks(self, tracks, market=None):
        ''' returns a list of tracks given a list of track IDs, URIs, or URLs

            Parameters:
                - tracks - a list of spotify URIs, URLs or IDs
                - market - an ISO 3166-1 alpha-2 country code.
        '''

        track_list = map(self._get_track_id, tracks)
        return self._get(API.TRACKS.value, ids=','.join(track_list), market=market)

    def artist(self, artist_id):
        ''' returns a single artist given the artist's ID, URI or URL

            Parameters:
                - artist_id - an artist ID, URI or URL
        '''

        id = self._get_artist_id(artist_id)
        return self._get(API.ARTIST.value.format(id=id))

    def artists(self, artists):
        ''' returns a list of artists given the artist IDs, URIs, or URLs

            Parameters:
                - artists - a list of  artist IDs, URIs or URLs
        '''

        artist_list = map(self._get_artist_id, artists)
        return self._get(API.ARTISTS.value, ids=','.join(artist_list))

    def artist_albums(self, artist_id, album_type=None, country=None, limit=20, offset=0):
        ''' Get Spotify catalog information about an artist's albums

            Parameters:
                - artist_id - the artist ID, URI or URL
                - album_type - 'album', 'single', 'appears_on', 'compilation'
                - country - limit the response to one particular country.
                - limit  - the number of albums to return
                - offset - the index of the first album to return
        '''

        id = self._get_artist_id(artist_id)
        return self._get(
            API.ARTIST_ALBUMS.value.format(id=id), album_type=album_type,
            country=country, limit=limit, offset=offset)

    def artist_top_tracks(self, artist_id, country='US'):
        ''' Get Spotify catalog information about an artist's top 10 tracks
            by country.

            Parameters:
                - artist_id - the artist ID, URI or URL
                - country - limit the response to one particular country.
        '''

        id = self._get_artist_id(artist_id)
        return self._get(API.ARTIST_TOP_TRACKS.value.format(id=id), country=country)

    def artist_related_artists(self, artist_id):
        ''' Get Spotify catalog information about artists similar to an
            identified artist. Similarity is based on analysis of the
            Spotify community's listening history.

            Parameters:
                - artist_id - the artist ID, URI or URL
        '''
        id = self._get_artist_id(artist_id)
        return self._get(API.ARTIST_RELATED_ARTISTS.value.format(id=id))

    def album(self, album_id):
        ''' returns a single album given the album's ID, URIs or URL

            Parameters:
                - album_id - the album ID, URI or URL
        '''

        id = self._get_album_id(album_id)
        return self._get(API.ALBUM.value.format(id=id))

    def album_tracks(self, album_id, limit=50, offset=0):
        ''' Get Spotify catalog information about an album's tracks

            Parameters:
                - album_id - the album ID, URI or URL
                - limit  - the number of items to return
                - offset - the index of the first item to return
        '''

        id = self._get_album_id(album_id)
        return self._get(API.ALBUM_TRACKS.value.format(id=id), limit=limit, offset=offset)

    def albums(self, albums):
        ''' returns a list of albums given the album IDs, URIs, or URLs

            Parameters:
                - albums - a list of  album IDs, URIs or URLs
        '''

        album_list = map(self._get_album_id, albums)
        return self._get(API.ALBUMS.value, ids=','.join(album_list))

    def search(self, url, q, limit=10, offset=0, market=None):
        ''' searches for an item

            Parameters:
                - q - the search query
                - limit  - the number of items to return
                - offset - the index of the first item to return
                - type - the type of item to return. One of 'artist', 'album',
                         'track' or 'playlist'
                - market - An ISO 3166-1 alpha-2 country code or the string from_token.
        '''
        return self._get(url, q=q, limit=limit, offset=offset, market=market)

    search_track = partialmethod(search, API.SEARCH_TRACK.value)
    search_album = partialmethod(search, API.SEARCH_ALBUM.value)
    search_artist = partialmethod(search, API.SEARCH_ARTIST.value)
    search_playlist = partialmethod(search, API.SEARCH_PLAYLIST.value)

    def user(self, user):
        ''' Gets basic profile information about a Spotify User

            Parameters:
                - user - the id of the user
        '''
        return self._get(API.USER.value.format(user_id=user))

    def current_user_playlists(self, limit=50, offset=0):
        """ Get current user playlists without required getting his profile
            Parameters:
                - limit  - the number of items to return
                - offset - the index of the first item to return
        """
        return self._get(API.MY_PLAYLISTS.value, limit=limit, offset=offset)

    def user_playlists(self, user, limit=50, offset=0):
        ''' Gets playlists of a user

            Parameters:
                - user - the id of the usr
                - limit  - the number of items to return
                - offset - the index of the first item to return
        '''
        return self._get(API.PLAYLISTS.value.format(user_id=user), limit=limit, offset=offset)

    def user_playlist(self, user, playlist_id=None, fields=None):
        ''' Gets playlist of a user
            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - fields - which fields to return
        '''
        if playlist_id is None:
            return self._get("users/%s/starred" % (user), fields=fields)
        id = self._get_playlist_id(playlist_id)
        return self._get(API.PLAYLIST.value.format(user_id=user, playlist_id=id), fields=fields)

    def user_playlist_tracks(self, user, playlist_id=None, fields=None,
                             limit=100, offset=0, market=None):
        ''' Get full details of the tracks of a playlist owned by a user.

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - fields - which fields to return
                - limit - the maximum number of tracks to return
                - offset - the index of the first track to return
                - market - an ISO 3166-1 alpha-2 country code.
        '''
        id = self._get_playlist_id(playlist_id)
        return self._get(
            API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=id),
            limit=limit, offset=offset, fields=fields, market=market)

    def user_playlist_create(self, user, name, public=True, description=''):
        ''' Creates a playlist for a user

            Parameters:
                - user - the id of the user
                - name - the name of the playlist
                - public - is the created playlist public
                - description - the description of the playlist
        '''
        data = {'name': name, 'public': public, 'description': description}
        return self._post(API.PLAYLISTS.value.format(user_id=user), payload=data)

    def user_playlist_change_details(
            self, user, playlist_id, name=None, public=None,
            collaborative=None, description=None):
        ''' Changes a playlist's name and/or public/private state

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - name - optional name of the playlist
                - public - optional is the playlist public
                - collaborative - optional is the playlist collaborative
                - description - the description of the playlist
        '''
        data = {}
        if isinstance(name, str):
            data['name'] = name
        if isinstance(public, bool):
            data['public'] = public
        if isinstance(collaborative, bool):
            data['collaborative'] = collaborative
        if isinstance(collaborative, str):
            data['description'] = description

        return self._put(API.PLAYLIST.value.format(user_id=user, playlist_id=playlist_id), payload=data)

    def user_playlist_unfollow(self, user, playlist_id):
        ''' Unfollows (deletes) a playlist for a user

            Parameters:
                - user - the id of the user
                - name - the name of the playlist
        '''
        return self._delete("users/%s/playlists/%s/followers" % (user, playlist_id))

    def user_playlist_add_tracks(self, user, playlist_id, tracks, position=None):
        ''' Adds tracks to a playlist

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - tracks - a list of track URIs, URLs or IDs
                - position - the position to add the tracks
        '''
        id = self._get_playlist_id(playlist_id)
        track_uris = map(self._get_track_uri, tracks)
        payload = {"uris": list(track_uris)}
        return self._post(
            API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=id),
            payload=payload, position=position)

    def user_playlist_replace_tracks(self, user, playlist_id, tracks):
        ''' Replace all tracks in a playlist

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - tracks - the list of track ids to add to the playlist
        '''
        id = self._get_playlist_id(playlist_id)
        track_uris = map(self._get_track_uri, tracks)
        payload = {"uris": list(track_uris)}
        return self._post(
            API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=id), payload=payload)

    def user_playlist_reorder_tracks(
            self, user, playlist_id, range_start, insert_before,
            range_length=1, snapshot_id=None):
        ''' Reorder tracks in a playlist

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - range_start - the position of the first track to be reordered
                - range_length - optional the number of tracks to be reordered (default: 1)
                - insert_before - the position where the tracks should be inserted
                - snapshot_id - optional playlist's snapshot ID
        '''
        id = self._get_playlist_id(playlist_id)
        payload = {"range_start": range_start,
                   "range_length": range_length,
                   "insert_before": insert_before}
        if snapshot_id:
            payload["snapshot_id"] = snapshot_id
        return self._put(
            API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=id), payload=payload)

    def user_playlist_remove_all_occurrences_of_tracks(
            self, user, playlist_id, tracks, snapshot_id=None):
        ''' Removes all occurrences of the given tracks from the given playlist

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - tracks - the list of track ids to add to the playlist
                - snapshot_id - optional id of the playlist snapshot

        '''

        id = self._get_playlist_id(playlist_id)
        track_uris = map(self._get_track_uri, tracks)
        payload = {"tracks": [{"uri": track} for track in track_uris]}
        if snapshot_id:
            payload["snapshot_id"] = snapshot_id
        return self._delete(
            API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=id), payload=payload)

    def user_playlist_remove_specific_occurrences_of_tracks(
            self, user, playlist_id, tracks, snapshot_id=None):
        ''' Removes all occurrences of the given tracks from the given playlist

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - tracks - an array of objects containing Spotify URIs of the tracks
                           to remove with their current positions in the playlist.
                    For example:
                        [
                          { "uri":"4iV5W9uYEdYUVa79Axb7Rh", "positions":[2] },
                          { "uri":"1301WleyT98MSxVHPZCA6M", "positions":[7] }
                        ]
                - snapshot_id - optional id of the playlist snapshot
        '''

        id = self._get_playlist_id(playlist_id)
        ftracks = []
        for tr in tracks:
            ftracks.append({
                "uri": self._get_uri("track", tr["uri"]),
                "positions": tr["positions"],
            })
        payload = {"tracks": ftracks}
        if snapshot_id:
            payload["snapshot_id"] = snapshot_id
        return self._delete(
            API.PLAYLIST_TRACKS.value.format(user_id=user, playlist_id=id), payload=payload)

    def user_playlist_follow_playlist(self, playlist_owner_id, playlist_id):
        '''
        Add the current authenticated user as a follower of a playlist.

        Parameters:
            - playlist_owner_id - the user id of the playlist owner
            - playlist_id - the id of the playlist

        '''
        return self._put(
            API.PLAYLIST_FOLLOWERS.value.format(
                owner_id=playlist_owner_id, playlist_id=playlist_id))

    def user_playlist_is_following(self, playlist_owner_id, playlist_id, user_ids):
        '''
        Check to see if the given users are following the given playlist

        Parameters:
            - playlist_owner_id - the user id of the playlist owner
            - playlist_id - the id of the playlist
            - user_ids - the ids of the users that you want to check to see if they follow the playlist. Maximum: 5 ids.

        '''
        return self._get(
            API.PLAYLIST_FOLLOWERS_CONTAINS.value.format(
                user_id=playlist_owner_id, playlist_id=playlist_id), ids=','.join(user_ids))

    def me(self):
        ''' Get detailed profile information about the current user.
            An alias for the 'current_user' method.
        '''
        return self._get(API.ME.value)

    def current_user(self):
        ''' Get detailed profile information about the current user.
            An alias for the 'me' method.
        '''
        return self.me()

    def current_user_saved_albums(self, limit=20, offset=0):
        ''' Gets a list of the albums saved in the current authorized user's
            "Your Music" library

            Parameters:
                - limit - the number of albums to return
                - offset - the index of the first album to return

        '''
        return self._get(API.MY_ALBUMS.value, limit=limit, offset=offset)

    def current_user_saved_tracks(self, limit=20, offset=0):
        ''' Gets a list of the tracks saved in the current authorized user's
            "Your Music" library

            Parameters:
                - limit - the number of tracks to return
                - offset - the index of the first track to return

        '''
        return self._get(API.MY_TRACKS.value, limit=limit, offset=offset)

    def current_user_followed_artists(self, limit=20, after=None):
        ''' Gets a list of the artists followed by the current authorized user

            Parameters:
                - limit - the number of tracks to return
                - after - ghe last artist ID retrieved from the previous request

        '''
        return self._get(
            API.MY_FOLLOWING.value, type='artist', limit=limit, after=after)

    def user_follow_artists(self, ids=[]):
        ''' Follow one or more artists
            Parameters:
                - ids - a list of artist IDs
        '''
        return self._put(API.MY_FOLLOWING.value, type='artist', ids=','.join(ids))

    def user_follow_users(self, ids=[]):
        ''' Follow one or more users
            Parameters:
                - ids - a list of user IDs
        '''
        return self._put(API.MY_FOLLOWING.value, type='user', ids=','.join(ids))

    def current_user_saved_tracks_delete(self, tracks=None):
        ''' Remove one or more tracks from the current user's
            "Your Music" library.

            Parameters:
                - tracks - a list of track URIs, URLs or IDs
        '''
        track_list = []
        if tracks is not None:
            track_list = map(self._get_track_id, tracks)
        return self._delete(API.MY_TRACKS.value, ids=','.join(track_list))

    def current_user_saved_tracks_contains(self, tracks=None):
        ''' Check if one or more tracks is already saved in
            the current Spotify user’s “Your Music” library.

            Parameters:
                - tracks - a list of track URIs, URLs or IDs
        '''
        track_list = []
        if tracks is not None:
            track_list = map(self._get_track_id, tracks)
        return self._get(API.MY_TRACKS_CONTAINS.value, ','.join(track_list))

    def current_user_saved_tracks_add(self, tracks=None):
        ''' Add one or more tracks to the current user's
            "Your Music" library.

            Parameters:
                - tracks - a list of track URIs, URLs or IDs
        '''
        track_list = []
        if tracks is not None:
            track_list = map(self._get_track_id, tracks)
        return self._put(API.MY_TRACKS.value, ids=','.join(track_list))

    def current_user_top_artists(self, limit=20, offset=0, time_range=TimeRange.MEDIUM_TERM.value):
        ''' Get the current user's top artists

            Parameters:
                - limit - the number of entities to return
                - offset - the index of the first entity to return
                - time_range - Over what time frame are the affinities computed
                  Valid-values: short_term, medium_term, long_term
        '''
        return self._get(
            API.MY_TOP.value.format(type='artists'), time_range=time_range,
            limit=limit, offset=offset)

    def current_user_top_tracks(self, limit=20, offset=0, time_range='medium_term'):
        ''' Get the current user's top tracks

            Parameters:
                - limit - the number of entities to return
                - offset - the index of the first entity to return
                - time_range - Over what time frame are the affinities computed
                  Valid-values: short_term, medium_term, long_term
        '''
        return self._get(
            API.MY_TOP.value.format(type='tracks'), time_range=time_range,
            limit=limit, offset=offset)

    def current_user_saved_albums_add(self, albums=[]):
        ''' Add one or more albums to the current user's
            "Your Music" library.
            Parameters:
                - albums - a list of album URIs, URLs or IDs
        '''
        album_list = map(self._get_album_id, albums)
        return self._put(API.MY_ALBUMS.value, ids=','.join(album_list))

    def featured_playlists(self, locale=None, country=None, timestamp=None, limit=20, offset=0):
        ''' Get a list of Spotify featured playlists

            Parameters:
                - locale - The desired language, consisting of a lowercase ISO
                  639 language code and an uppercase ISO 3166-1 alpha-2 country
                  code, joined by an underscore.

                - country - An ISO 3166-1 alpha-2 country code.

                - timestamp - A timestamp in ISO 8601 format:
                  yyyy-MM-ddTHH:mm:ss. Use this parameter to specify the user's
                  local time to get results tailored for that specific date and
                  time in the day

                - limit - The maximum number of items to return. Default: 20.
                  Minimum: 1. Maximum: 50

                - offset - The index of the first item to return. Default: 0
                  (the first object). Use with limit to get the next set of
                  items.
        '''
        return self._get(
            API.FEATURED_PLAYLISTS.value, locale=locale, country=country,
            timestamp=timestamp, limit=limit, offset=offset)

    def new_releases(self, country=None, limit=20, offset=0):
        ''' Get a list of new album releases featured in Spotify

            Parameters:
                - country - An ISO 3166-1 alpha-2 country code.

                - limit - The maximum number of items to return. Default: 20.
                  Minimum: 1. Maximum: 50

                - offset - The index of the first item to return. Default: 0
                  (the first object). Use with limit to get the next set of
                  items.
        '''
        return self._get(
            API.NEW_RELEASES.value, country=country, limit=limit, offset=offset)

    def categories(self, country=None, locale=None, limit=20, offset=0):
        ''' Get a list of new album releases featured in Spotify

            Parameters:
                - country - An ISO 3166-1 alpha-2 country code.
                - locale - The desired language, consisting of an ISO 639
                  language code and an ISO 3166-1 alpha-2 country code, joined
                  by an underscore.

                - limit - The maximum number of items to return. Default: 20.
                  Minimum: 1. Maximum: 50

                - offset - The index of the first item to return. Default: 0
                  (the first object). Use with limit to get the next set of
                  items.
        '''
        return self._get(
            API.CATEGORIES.value, country=country, locale=locale, limit=limit, offset=offset)

    def category_playlists(self, category_id=None, country=None, limit=20, offset=0):
        ''' Get a list of new album releases featured in Spotify

            Parameters:
                - category_id - The Spotify category ID for the category.

                - country - An ISO 3166-1 alpha-2 country code.

                - limit - The maximum number of items to return. Default: 20.
                  Minimum: 1. Maximum: 50

                - offset - The index of the first item to return. Default: 0
                  (the first object). Use with limit to get the next set of
                  items.
        '''
        return self._get(
            API.CATEGORY_PLAYLISTS.value.format(id=category_id),
            country=country, limit=limit, offset=offset)

    def recommendations(
            self, seed_artists=None, seed_genres=None,
            seed_tracks=None, limit=20, country=None, **kwargs):
        ''' Get a list of recommended tracks for one to five seeds.

            Parameters:
                - seed_artists - a list of artist IDs, URIs or URLs

                - seed_tracks - a list of artist IDs, URIs or URLs

                - seed_genres - a list of genre names. Available genres for
                  recommendations can be found by calling recommendation_genre_seeds

                - country - An ISO 3166-1 alpha-2 country code. If provided, all
                  results will be playable in this country.

                - limit - The maximum number of items to return. Default: 20.
                  Minimum: 1. Maximum: 100

                - min/max/target_<attribute> - For the tuneable track attributes listed
                  in the documentation, these values provide filters and targeting on
                  results.
        '''
        params = dict(limit=limit)
        if seed_artists:
            params['seed_artists'] = ','.join(map(self._get_artist_id, seed_artists))
        if seed_genres:
            params['seed_genres'] = ','.join(seed_genres)
        if seed_tracks:
            params['seed_tracks'] = ','.join(map(self._get_track_id, seed_tracks))
        if country:
            params['market'] = country

        for attribute in list(AudioFeature):
            for prefix in ["min_", "max_", "target_"]:
                param = prefix + attribute.value
                if param in kwargs:
                    params[param] = kwargs[param]

        return self._get(API.RECOMMENDATIONS.value, **params)

    def recommendation_genre_seeds(self):
        ''' Get a list of genres available for the recommendations function.
        '''
        return self._get(API.RECOMMENDATIONS_GENRES.value)

    def audio_analysis(self, track=None):
        ''' Get audio analysis for a track based upon its Spotify ID
            Parameters:
                - track - a track URI, URL or ID
        '''
        id = self._get_track_id(track)
        return self._get(API.AUDIO_ANALYSIS.value.format(id=id))

    def audio_features(self, track=None, tracks=[]):
        ''' Get audio features for one or multiple tracks based upon their Spotify IDs
            Parameters:
                - track - a track URI, URL or ID
                - tracks - a list of track URIs, URLs or IDs, maximum: 50 ids
        '''
        assert len(tracks) <= 50

        if track:
            id = self._get_track_id(track)
            results = self._get(API.AUDIO_FEATURES_SINGLE.value.format(id=id))
        else:
            tracks = map(self._get_track_id, tracks)
            results = self._get(API.AUDIO_FEATURES_MULTIPLE.value, ids=','.join(tracks))

        if 'audio_features' in results:
            return results['audio_features']
        else:
            return results

    def devices(self):
        ''' Get a list of user's available devices.
        '''
        return self._get(API.DEVICES.value)

    def get_device(self, device=None):
        '''Get Spotify device based on name

        :param str, optional device: device name or ID
        :param str, optional field: device attribute to return

        str or dict: Spotify device
        '''

        devices = self.devices().devices
        device_names = ', '.join([d.name for d in devices])
        device_name_or_id = device
        if not device_name_or_id:
            device = first(devices, key=attrgetter('is_active'))
            if not device:
                raise ValueError(f'''
        There's no active device.
        Possible devices: {device_names}''')
        else:
            device = first(devices, key=lambda d: device_name_or_id in (d.name, d.id))
            if not device:
                raise ValueError(f'''
        Device {device_name_or_id} doesn't exist.
        Possible devices: {device_names}''')

        return device

    def current_playback(self, market=None):
        ''' Get information about user's current playback.

            Parameters:
                - market - an ISO 3166-1 alpha-2 country code.
        '''
        return self._get(API.PLAYER.value, market=market)

    def current_user_recently_played(self, limit=50):
        ''' Get the current user's recently played tracks

            Parameters:
                - limit - the number of entities to return
        '''
        return self._get(API.RECENTLY_PLAYED.value, limit=limit)

    def currently_playing(self, market=None):
        ''' Get user's currently playing track.

            Parameters:
                - market - an ISO 3166-1 alpha-2 country code.
        '''
        return self._get(API.CURRENTLY_PLAYING.value, market=market)

    def transfer_playback(self, device_id, force_play=True):
        ''' Transfer playback to another device.
            Note that the API accepts a list of device ids, but only
            actually supports one.

            Parameters:
                - device_id - transfer playback to this device
                - force_play - true: after transfer, play. false:
                               keep current state.
        '''
        data = {
            'device_ids': [device_id],
            'play': force_play
        }
        return self._put(API.PLAYER.value, payload=data)

    def start_playback(self, device_id=None, artist=None, album=None, playlist=None, tracks=None, offset=None):
        ''' Start or resume user's playback.

            Parameters:
                - device_id - device target for playback
                - playlist - spotify playlist to play
                - artist - spotify artist to play
                - album - spotify album to play
                - tracks - spotify tracks to play
                - offset - offset into context by index or track
        '''
        data = {}
        if playlist:
            data['context_uri'] = self._get_playlist_uri(playlist)
        elif album:
            data['context_uri'] = self._get_album_uri(album)
        elif artist:
            data['context_uri'] = self._get_artist_uri(artist)
        elif tracks:
            data['uris'] = list(map(self._get_track_uri, tracks))

        if isinstance(offset, int):
            data['offset'] = dict(position=offset)
        elif isinstance(offset, str):
            data['offset'] = dict(uri=offset)

        return self._put(API.PLAY.value, device_id=device_id, payload=data)

    def pause_playback(self, device_id=None):
        ''' Pause user's playback.

            Parameters:
                - device_id - device target for playback
        '''
        return self._put(API.PAUSE.value, device_id=device_id)

    def next_track(self, device_id=None):
        ''' Skip user's playback to next track.

            Parameters:
                - device_id - device target for playback
        '''
        return self._post(API.NEXT.value, device_id=device_id)

    def previous_track(self, device_id=None):
        ''' Skip user's playback to previous track.

            Parameters:
                - device_id - device target for playback
        '''
        return self._post(API.PREVIOUS.value, device_id=device_id)

    def seek_track(self, position_ms, device_id=None):
        ''' Seek to position in current track.

            Parameters:
                - position_ms - position in milliseconds to seek to
                - device_id - device target for playback
        '''
        if not isinstance(position_ms, int):
            logger.warning('position_ms must be an integer')
            return
        return self._put(API.SEEK.value, position_ms=position_ms, device_id=device_id)

    def repeat(self, state, device_id=None):
        ''' Set repeat mode for playback.

            Parameters:
                - state - `track`, `context`, or `off`
                - device_id - device target for playback
        '''
        if state not in ['track', 'context', 'off']:
            logger.warning('Invalid state')
            return

        self._put(API.REPEAT.value, state=state, device_id=device_id)

    def volume(self, volume_percent: int=None, device_id: str=None):
        ''' Get or set playback volume.

            Parameters:
                - volume_percent - volume between 0 and 100
                - device_id - device target for playback
        '''
        if volume_percent is None:
            return self.get_device(device=device_id).volume_percent

        assert 0 <= volume_percent <= 100

        self._put(API.VOLUME.value, volume_percent=volume_percent, device_id=device_id)

    def shuffle(self, state, device_id=None):
        ''' Toggle playback shuffling.

            Parameters:
                - state - true or false
                - device_id - device target for playback
        '''
        if not isinstance(state, bool):
            logger.warning('State must be a boolean')
            return

        state = str(state).lower()
        self._put(API.SHUFFLE.value, state=state, device_id=device_id)

    def _get_id(self, type, result):
        if isinstance(result, str):
            fields = result.split(':')
            if len(fields) >= 3:
                if type != fields[-2]:
                    logger.warning('Expected id of type %s but found type %s %s',
                                   type, fields[-2], result)
                return fields[-1]
            fields = result.split('/')
            if len(fields) >= 3:
                itype = fields[-2]
                if type != itype:
                    logger.warning('Expected id of type %s but found type %s %s',
                                   type, itype, result)
                return fields[-1]
        elif isinstance(result, SpotifyResult):
            return result.id

        return result

    _get_track_id = partialmethod(_get_id, 'track')
    _get_artist_id = partialmethod(_get_id, 'artist')
    _get_album_id = partialmethod(_get_id, 'album')
    _get_playlist_id = partialmethod(_get_id, 'playlist')

    def _get_uri(self, type, result):
        return 'spotify:' + type + ":" + self._get_id(type, result)

    _get_track_uri = partialmethod(_get_uri, 'track')
    _get_artist_uri = partialmethod(_get_uri, 'artist')
    _get_album_uri = partialmethod(_get_uri, 'album')
    _get_playlist_uri = partialmethod(_get_uri, 'playlist')
