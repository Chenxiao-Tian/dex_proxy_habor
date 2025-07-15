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

py_dex_common_path = os.path.abspath("../py_dex_common")

setuptools.setup(
    name="dex_proxy",
    version=f'{tag}+g{rev}',
    packages=setuptools.find_packages(),
    install_requires=[
        # Our old pip doesn't support relative paths
        #"py_dex_common @ file:../py_dex_common",
        f"py_dex_common @ file://{py_dex_common_path}",
        "gte-py @ git+https://github.com/liquid-labs-inc/gte-python-sdk.git@497f09a46dbf99ca22e4119b5865d1ff67d69b8f"
    ]
)
