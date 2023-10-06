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
        'boto3==1.26.55',
        'eth-account==0.8.0',
        'ujson==5.7.0',
        # CVE-2023-37276
        'aiohttp>=3.8.5',
        'pantheon @ git+ssh://bitbucket.org/kenetic/pytheon.git@aiohttp-upgrade-3.8.5',
        'pyutils @ git+ssh://bitbucket.org/kenetic/pyutils.git@c2f85f56070aa81ad1a0e494432ab37c5c44d5bc',
        # refs/tags/v6.0.0-beta.8
        # require w3 beta 6 to fix dependency conflict with solana/websockets.
        'Web3 @ git+https://github.com/ethereum/web3.py.git@de95191dea8eb56e5176693946fb1e50957b8a5c',
    ]
)
