from setuptools import setup, find_packages

setup(
    name="openhac",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "skidl>=1.0.0",
        "z3-solver>=4.13.0",
        "requests>=2.31.0",
    ],
)
