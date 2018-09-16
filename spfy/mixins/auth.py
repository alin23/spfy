import socket
import threading
import uuid
from pathlib import Path
from wsgiref.simple_server import make_server

import hug
from cachecontrol import CacheControlAdapter
from cachecontrol.caches.file_cache import FileCache
from oauthlib.oauth2 import BackendApplicationClient
from pony.orm import get
from requests_oauthlib import OAuth2Session

from .. import config, logger, root
from ..cache import User, db_session, select
from ..constants import API, AllScopes, AuthFlow
from ..exceptions import SpotifyCredentialsException

AUTH_HTML_FILE = root / "html" / "auth_message.html"
CACHE_FILE = Path.home() / ".cache" / "spfy" / ".web_cache"


class AuthMixin:
    def __init__(
        self,
        *args,
        client_id=None,
        client_secret=None,
        redirect_uri=None,
        user_id=None,
        username=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.client_id = client_id or config.app.client_id
        self.client_secret = client_secret or config.app.client_secret
        self.redirect_uri = self._get_redirect_uri(redirect_uri)
        self.user_id = user_id
        self.username = username
        self.callback_reached = threading.Event()
        self.flow = None
        self.session = None

    @staticmethod
    def _get_redirect_uri(redirect_uri):
        redirect_uri = (
            redirect_uri
            or config.app.redirect_uri
            or f"http://{socket.gethostname()}.local"
        )
        if config.auth.callback.enabled and config.auth.callback.port and redirect_uri:
            redirect_uri += f":{config.auth.callback.port}"
        return redirect_uri

    @staticmethod
    def get_session(*args, **kwargs):
        session = OAuth2Session(*args, **kwargs)
        cache_adapter = CacheControlAdapter(
            cache=FileCache(CACHE_FILE),
            pool_connections=config.http.connections,
            pool_maxsize=config.http.connections,
            max_retries=config.http.retries,
        )
        session.mount("http://", cache_adapter)
        return session

    @property
    @db_session
    def user(self):
        return User[self.user_id]

    @property
    def is_authenticated(self):
        return bool(self.session and self.session.authorized)

    @db_session
    def authenticate_user(
        self,
        username=None,
        email=None,
        code=None,
        state=None,
        auth_response=None,
        scope=AllScopes,
    ):
        self.flow = AuthFlow.AUTHORIZATION_CODE
        session = self.session or self.get_session(
            self.client_id,
            redirect_uri=self.redirect_uri,
            scope=scope,
            auto_refresh_url=API.TOKEN.value,
        )
        if self.user_id:
            user = User.get(id=self.user_id)
            if user and user.token:
                session.token = user.token
                session.token_updater = User.token_updater(user.id)
                return session

        if username or email:
            user = get(u for u in User if u.username == username or u.email == email)
            if user:
                self.user_id = user.id
                self.username = user.username
                session.token = user.token
                session.token_updater = User.token_updater(user.id)
                return session

        if code or auth_response:
            token = session.fetch_token(
                token_url=API.TOKEN.value,
                client_id=self.client_id,
                client_secret=self.client_secret,
                code=code,
                state=state,
                authorization_response=auth_response,
            )
            user_details = self.current_user()
            user = (
                select(
                    u
                    for u in User
                    if u.username == user_details.id or u.email == user_details.email
                )
                .for_update()
                .get()
            )
            if user:
                user.token = token
                if user.id != self.user_id:
                    self.user_id = user.id
                    self.username = user.username
            elif self.user_id:
                user = User.get_for_update(id=self.user_id)
                if user:
                    user.token = token
            if not user:
                self.user_id = self.user_id or uuid.uuid4()
                user_details["user_id"] = self.user_id
                user_details["token"] = token
                user = User.from_dict(user_details)
                self.username = user.username
            return session

        return session

    @db_session
    def authenticate_server(self):
        self.flow = AuthFlow.CLIENT_CREDENTIALS
        default_user = User.default()
        self.user_id = default_user.id
        self.username = default_user.username
        session = self.session or self.get_session(
            client=BackendApplicationClient(self.client_id)
        )
        session.token_updater = User.token_updater(default_user.id)
        if default_user.token:
            session.token = default_user.token
        else:
            default_user.token = session.fetch_token(
                token_url=API.TOKEN.value,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        return session

    def authenticate(self, flow=config.auth.flow, **auth_params):
        if not (self.client_id and self.client_secret):
            raise SpotifyCredentialsException

        self.flow = AuthFlow(flow)
        if self.flow == AuthFlow.CLIENT_CREDENTIALS:
            self.session = self.authenticate_server()
        elif self.flow == AuthFlow.AUTHORIZATION_CODE:
            self.session = self.authenticate_user(**auth_params)
            if not self.session.token:
                if config.auth.callback.enabled:
                    self.start_callback()
                authorization_url, _ = self.session.authorization_url(
                    API.AUTHORIZE.value
                )
                if config.auth.send_auth_url_to_email:
                    email = auth_params.get("email") or config.auth.email
                    self.send_auth_email(email, authorization_url)
                else:
                    print(f"Login here: {authorization_url}")
                self.wait_for_authorization()

    def wait_for_authorization(self):
        if not config.auth.callback.enabled:
            url = input("Paste the URL you are redirected to:")
            self.session = self.authenticate_user(auth_response=url)
        else:
            self.callback_reached.wait(config.auth.callback.timeout)
            self.stop_callback()

    def stop_callback(self):
        if self.httpd:
            self.httpd.shutdown()

    def start_callback(self):
        self.callback_reached.clear()

        # pylint: disable=unused-variable

        @hug.get("/", output=hug.output_format.html)
        def callback(code: hug.types.text, state: hug.types.text):
            html = AUTH_HTML_FILE.read_text()  # pylint: disable=no-member
            try:
                self.session = self.authenticate_user(code=code, state=state)
                html = html.replace("SPOTIFY_AUTH_MESSAGE", "Successfully logged in!")
                html = html.replace("BACKGROUND_COLOR", "#65D46E")
            except Exception as exc:
                logger.exception(exc)
                html = html.replace(
                    "SPOTIFY_AUTH_MESSAGE", "Could not get authorization token."
                )
                html = html.replace("BACKGROUND_COLOR", "#EC2E50")
            finally:
                self.callback_reached.set()
            return html

        api = __hug__.http.server(None)  # pylint: disable=undefined-variable
        self.httpd = make_server("", config.auth.callback.port, api)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
