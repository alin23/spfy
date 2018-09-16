import ujson as json


class SpotifyException(Exception):
    def __init__(
        self, *args, status_code=None, headers=None, text=None, url=None, **kwargs
    ):  # pylint: disable=unused-argument
        super().__init__()
        self.http_status_code = status_code
        self.headers = headers or {}
        if text and text != "null":
            try:
                response = json.loads(text)
                self.msg = f'{url}:\n {response["error"]["message"]}'
            except:
                self.msg = f"{url}: error"
        else:
            self.msg = f"{url}: error"

    def __str__(self):
        return f"""
        HTTP Status Code: {self.http_status_code}
        {self.msg}"""


class SpotifyRateLimitException(SpotifyException):
    def __init__(self, *args, retry_after=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class SpotifyForbiddenException(SpotifyException):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class SpotifyDeviceUnavailableException(SpotifyException):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class SpotifyCredentialsException(Exception):
    def __str__(self):
        return """
        You need to set your Spotify API credentials in ~/.config/spfy/config.toml

        Get your credentials at
            https://developer.spotify.com/my-applications
        """


class SpotifyAuthException(Exception):
    def __str__(self):
        return """
        You need to authenticate before making any request.
        """


class NoDatabaseConnection(Exception):
    pass
