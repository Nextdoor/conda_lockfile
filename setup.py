from setuptools import setup

setup(
    name='conda_lockfile',
    version='0.1',
    packages=['conda_lockfile'],
    entry_points={
        'console_scripts': ['conda_lockfile = conda_lockfile.cli:main'],
    },
)
