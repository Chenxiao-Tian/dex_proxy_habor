import os
import subprocess
import sys

import setuptools


def run(*cmd):
    wd = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, cwd=wd)
    return p.stdout.read().decode().rstrip()


tag = run('git', 'for-each-ref', '--format=%(refname:short)',
          '--sort=-authordate', '--count=1', 'refs/tags')
rev = run('git', 'rev-parse', '--short=8', 'HEAD')

setuptools.setup(
    name='dex_proxy',
    version=f'{tag}+{rev}',
    py_modules=[],
    install_requires=[
        'aiohttp==3.7.4.post0',
        'aio-pika==6.8.0',
        'boto3==1.26.55',
        'eth-account==0.8.0',
        'ujson==4.2.0',
        'pantheon @ git+ssh://bitbucket.org/kenetic/pytheon.git@f051f908f550e934b6a6ce5881d5d8b8e32b3fda',
        'pyutils @ git+ssh://bitbucket.org/kenetic/pyutils.git@bd39118c46635110a3b7bbdf767c7e59fe31924c',
        # refs/tags/v6.0.0-beta.8
        # require w3 beta 6 to fix dependency conflict with solana/websockets.
        'Web3 @ git+https://github.com/ethereum/web3.py.git@de95191dea8eb56e5176693946fb1e50957b8a5c',
    ]
)
