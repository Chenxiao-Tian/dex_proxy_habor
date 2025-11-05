from setuptools import setup, find_packages

setup(
    name="vasquez",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.10",
    install_requires=[
        "gte_py@git+https://github.com/liquid-labs-inc/gte-python-sdk@b8acbc4#egg=gte-py",
        "async_timeout",
        "dotenv"
    ],
)
