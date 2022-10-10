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
    install_requires=[
        'aiohttp==3.7.4',
        'aio-pika==6.8.0',
        'boto3==1.9.106',
        'eth-account>=0.4.0,<0.6.0',
        'web3==5.29.2',
        'pantheon @ git+ssh://bitbucket.org/kenetic/pytheon.git@pytheon-1.0.0',
        'pyutils @ git+ssh://bitbucket.org/kenetic/pyutils.git@920dc278d9997a78eff70bf2fe75284f63d97669',
    ]
)
