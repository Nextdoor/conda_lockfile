from setuptools import setup

setup(
    name='conda-ndenv',
    version='0.1',
    packages=['conda_ndenv'],
    entry_points={
        'console_scripts': ['conda_ndenv = conda_ndenv.cli:main',
    },
)
