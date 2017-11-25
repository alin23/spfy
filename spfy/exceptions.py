class SpotifyException(Exception):
    def __init__(self, response=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http_status_code = response.status_code
        self.headers = response.headers or {}

        if response.text and len(response.text) > 0 and response.text != 'null':
            self.msg = f'{response.url}:\n {response.json()["error"]["message"]}'
        else:
            self.msg = f'{response.url}: error'

    def __str__(self):
        return f'''
        HTTP Status Code: {self.http_status_code}
        {self.msg}'''


class SpotifyRateLimitException(SpotifyException):
    def __init__(self, retry_after=0, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class SpotifyForbiddenException(SpotifyException):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class SpotifyCredentialsException(Exception):
    def __str__(self):
        return '''
        You need to set your Spotify API credentials in ~/.config/spfy/config.toml

        Get your credentials at
            https://developer.spotify.com/my-applications
        '''


class SpotifyAuthException(Exception):
    def __str__(self):
        return '''
        You need to authenticate before making any request.
        '''
