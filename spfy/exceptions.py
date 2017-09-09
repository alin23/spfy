class SpotifyException(Exception):
    def __init__(self, response):
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
    pass


class SpotifyForbiddenException(SpotifyException):
    pass


class SpotifyCredentialsException(Exception):
    def __str__(self):
        return '''
        You need to set your Spotify API credentials. You can do this by
        setting environment variables like so:

        export SPOTIPY_CLIENT_ID='your-spotify-client-id'
        export SPOTIPY_CLIENT_SECRET='your-spotify-client-secret'
        export SPOTIPY_REDIRECT_URI='your-app-redirect-url'

        Get your credentials at
            https://developer.spotify.com/my-applications
        '''


class SendGridCredentialsException(Exception):
    def __str__(self):
        return '''
            You need to set your SendGrid API credentials. You can do this by
            setting environment variables like so:

            export SENDGRID_API_KEY='your-sendgrid-api-key'
            export SENDGRID_SENDER='your-sendgrid-sender-email'
        '''
