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
        'pantheon @ git+ssh://git@bitbucket.org/kenetic/pytheon.git@pytheon-1.2.26',
        'pyutils @ git+ssh://bitbucket.org/kenetic/pyutils.git@abcdfe5cc850bec0ced3f7e8c8097e7329aa50cf'
    ]
)
