import setuptools

setuptools.setup(
    name="uniswap_shared",
    packages=["uniswap_shared"],
    install_requires=[
        'msgpack==1.0.8',
        'orjson==3.10.18',
        "pyutils @ git+ssh://git@bitbucket.org/kenetic/pyutils.git@pyutils-1.18.11",
        "fastopenapi"
    ]
)
