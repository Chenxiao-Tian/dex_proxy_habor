import os
import subprocess
import sys
import re
import setuptools


def get_version_from_git_tag(tag):
    match = re.search(r'(\d+\.\d+\.\d+(?:[^\s]*)?)$', tag)
    if not match:
        raise ValueError(f"Could not extract version from tag: {tag}")
    return match.group(1)


def run(*cmd):
    wd = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, cwd=wd)
    return p.stdout.read().decode().rstrip()


tag = run('git', 'for-each-ref', '--format=%(refname:short)', '--sort=-authordate', '--count=1', 'refs/tags')
tag = get_version_from_git_tag(tag)
rev = run('git', 'rev-parse', '--short=8', 'HEAD')

setuptools.setup(
    name="py_dex_common",
    version=f'{tag}+g{rev}',
    packages=setuptools.find_packages(), 
    install_requires=[
        'msgpack==1.0.8',
        'orjson==3.10.18',
        "pyutils @ git+ssh://git@bitbucket.org/kenetic/pyutils.git@pyutils-1.18.0",
        "fastopenapi"
    ]
)