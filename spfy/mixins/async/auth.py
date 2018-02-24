import uuid
import socket
import asyncio
import threading
from pathlib import Path

import aiohttp
import aiohttp.web
from oauthlib.oauth2 import BackendApplicationClient
from aiohttp.web_runner import GracefulExit

from ... import root, config, logger
from ...cache import User, get, select, db_session
from ...constants import API, AuthFlow, AllScopes
from ...exceptions import SpotifyCredentialsException
from .aiohttp_oauthlib import OAuth2Session

AUTH_HTML_FILE = root / 'html' / 'auth_message.html'
CACHE_FILE = Path.home() / '.cache' / 'spfy' / '.web_cache'

web_app = aiohttp.web.Application()


def run_app():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    aiohttp.web.run_app(web_app, host='0.0.0.0', port=config.auth.callback.port, handle_signals=False)


class AuthMixin:
    def __init__(self, *args, client_id=None, client_secret=None, redirect_uri=None, user_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.client_id = client_id or config.app.client_id
        self.client_secret = client_secret or config.app.client_secret
        self.redirect_uri = self._get_redirect_uri(redirect_uri)

        self.session = None
        self.user_id = user_id

        self.callback_reached = threading.Event()

    @staticmethod
    def _get_redirect_uri(redirect_uri):
        redirect_uri = (redirect_uri or config.app.redirect_uri or f'http://{socket.gethostname()}.local')

        if config.auth.callback.enabled and config.auth.callback.port and redirect_uri:
            redirect_uri += f':{config.auth.callback.port}'

        return redirect_uri

    @staticmethod
    def get_session(*args, **kwargs):
        session = OAuth2Session(*args, **kwargs)
        return session

    @property
    @db_session
    def user(self):
        return User[self.user_id]

    @property
    def is_authenticated(self):
        return bool(self.session and self.session.authorized)

    @db_session
    async def authenticate_user(
        self, username=None, email=None, code=None, state=None, auth_response=None, scope=AllScopes
    ):
        session = self.session or self.get_session(
            self.client_id, redirect_uri=self.redirect_uri, scope=scope, auto_refresh_url=API.TOKEN.value
        )

        if self.user_id:
            user = User.get(id=self.user_id)
            if user:
                session.token = user.token
                session.token_updater = User.token_updater(user.id)
                return session

        if username or email:
            user = get(u for u in User if u.username == username or u.email == email)
            if user:
                self.user_id = user.id
                session.token = user.token
                session.token_updater = User.token_updater(user.id)
                return session

        if code or auth_response:
            token = await session.fetch_token(
                token_url=API.TOKEN.value,
                client_id=self.client_id,
                client_secret=self.client_secret,
                code=code,
                state=state,
                authorization_response=auth_response
            )

            user_details = await self.current_user()
            user = select(u for u in User
                          if u.username == user_details.id or u.email == user_details.email).for_update().get()

            if user:
                user.token = token
                if user.id != self.user_id:
                    self.user_id = user.id
            elif self.user_id:
                user = User.get_for_update(id=self.user_id)
                if user:
                    user.token = token

            if not user:
                self.user_id = self.user_id or uuid.uuid4()
                user_details['user_id'] = self.user_id
                user_details['token'] = token
                user = User.from_dict(user_details)

            return session

        return session

    @db_session
    async def authenticate_server(self):
        default_user = User.default()
        self.user_id = default_user.id

        session = self.session or self.get_session(client=BackendApplicationClient(self.client_id))
        session.token_updater = User.token_updater(default_user.id)

        if default_user.token:
            session.token = default_user.token
        else:
            default_user.token = await session.fetch_token(
                token_url=API.TOKEN.value, client_id=self.client_id, client_secret=self.client_secret
            )

        return session

    async def authenticate(self, flow=config.auth.flow, **auth_params):
        if not (self.client_id and self.client_secret):
            raise SpotifyCredentialsException

        flow = AuthFlow(flow)
        if flow == AuthFlow.CLIENT_CREDENTIALS:
            self.session = await self.authenticate_server()
        elif flow == AuthFlow.AUTHORIZATION_CODE:
            self.session = await self.authenticate_user(**auth_params)
            if not self.session.token:
                if config.auth.callback.enabled:
                    self.start_callback()

                authorization_url, _ = self.session.authorization_url(API.AUTHORIZE.value)
                if config.auth.send_auth_url_to_email:
                    email = auth_params.get('email') or config.auth.email
                    self.send_auth_email(email, authorization_url)
                else:
                    print(f'Login here: {authorization_url}')

                await self.wait_for_authorization()

    async def wait_for_authorization(self):
        if not config.auth.callback.enabled:
            url = input('Paste the URL you are redirected to:')
            self.session = await self.authenticate_user(auth_response=url)
        else:
            self.callback_reached.wait(config.auth.callback.timeout)
            await self.stop_callback()

    @staticmethod
    async def stop_callback():
        try:
            await aiohttp.request('GET', f'http://localhost:{config.auth.callback.port}')
        except aiohttp.client_exceptions.ServerDisconnectedError:
            pass

    def start_callback(self):
        self.callback_reached.clear()

        async def callback(request):
            if self.callback_reached.is_set():
                raise GracefulExit

            code = request.query['code']
            state = request.query.get('code')

            html = AUTH_HTML_FILE.read_text()
            try:
                self.session = asyncio.run_coroutine_threadsafe(
                    self.authenticate_user(code=code, state=state), loop=self.loop
                ).result(config.auth.callback.timeout)
                html = html.replace('SPOTIFY_AUTH_MESSAGE', 'Successfully logged in!')
                html = html.replace('BACKGROUND_COLOR', '#65D46E')
            except Exception as exc:
                logger.exception(exc)
                html = html.replace('SPOTIFY_AUTH_MESSAGE', 'Could not get authorization token.')
                html = html.replace('BACKGROUND_COLOR', '#EC2E50')
            finally:
                self.callback_reached.set()

            return aiohttp.web.Response(body=html, content_type='text/html')

        web_app.router.add_get('/', callback)

        threading.Thread(target=run_app, daemon=True).start()
