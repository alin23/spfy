import os

from setuptools import setup, find_packages

with open('spfy/__init__.py', 'r') as f:
    for line in f:
        if line.startswith('__version__'):
            version = line.strip().split('=')[1].strip(' \'"')
            break
    else:
        version = '0.0.1'

with open('README.md', 'rb') as f:
    readme = f.read().decode('utf-8')

REQUIRES = [
    'addict',
    'backoff',
    'daiquiri',
    'fire',
    'first',
    'gunicorn',
    'hug',
    'oauthlib',
    'orderby',
    'requests',
    'requests_oauthlib',
    'sendgrid',
]
if os.uname().sysname == 'Linux':
    REQUIRES.append('pyalsaaudio')

setup(
    name='spfy',
    version=version,
    description='',
    long_description=readme,
    author='Alin Panaitiu',
    author_email='alin.p32@gmail.com',
    maintainer='Alin Panaitiu',
    maintainer_email='alin.p32@gmail.com',
    url='https://github.com/alin23/spfy',
    license='MIT/Apache-2.0',

    keywords=[
        'spotify', 'spfy'
    ],

    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
    ],

    install_requires=REQUIRES,
    tests_require=['coverage', 'pytest'],

    packages=find_packages(),
    entry_points={
        'console_scripts': ['spotify = spfy.wrapper:main']
    },

)
