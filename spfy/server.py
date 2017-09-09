from gunicorn.app.base import BaseApplication


class StandaloneApplication(BaseApplication):
    def __init__(self, app, **options):
        self.options = options
        self.application = app
        super(StandaloneApplication, self).__init__()

    def load_config(self):
        config = {
            k: v for k, v in self.options.items()
            if k in self.cfg.settings and v is not None
        }
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application
