import pathlib

from setuptools import find_packages, setup

CONFIGDIR = pathlib.Path.home() / ".config" / "spfy"
CONFIGDIR.mkdir(parents=True, exist_ok=True)
with open("spfy/__init__.py", "r") as f:
    for line in f:
        if line.startswith("__version__"):
            version = line.strip().split("=")[1].strip(" '\"")
            break

    else:
        version = "0.0.1"
with open("README.md", "rb") as f:
    readme = f.read().decode("utf-8")
REQUIRES = [
    "addict",
    "aiohttp",
    "aioredis",
    "async_generator",
    "asyncpg",
    "backoff",
    "cachecontrol",
    "cached_property",
    "colorthief",
    "fire",
    "first",
    "gunicorn",
    "hug",
    "kick>=1.1.0",
    "lockfile",
    "mailer",
    "msgpack",
    "oauthlib",
    "pandas",
    "pony",
    "psycopg2-binary",
    "pycountry",
    "python-unsplash-async>=1.0.4",
    "urllib3",
    "requests",
    "requests_oauthlib",
    "tenacity",
    "ujson",
]
try:
    import sys

    if sys.platform == "Linux":
        REQUIRES.append("pyalsaaudio")
except:
    pass
setup(
    name="spfy",
    version=version,
    description="",
    long_description=readme,
    author="Alin Panaitiu",
    author_email="alin.p32@gmail.com",
    maintainer="Alin Panaitiu",
    maintainer_email="alin.p32@gmail.com",
    url="https://github.com/alin23/spfy",
    license="MIT/Apache-2.0",
    keywords=["spotify", "spfy"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Apache Software License",
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
    ],
    install_requires=REQUIRES,
    tests_require=["pytest"],
    packages=find_packages(),
    package_data={"spfy": ["config/*.toml", "html/*.html"]},
    data_files=[(str(CONFIGDIR), ["spfy/config/config.toml"])],
    entry_points={
        "console_scripts": [
            "spotify = spfy.wrapper:main",
            "spotify_async = spfy.asynch.wrapper:main",
        ]
    },
)
