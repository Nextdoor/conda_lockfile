from setuptools import setup

setup(
    name='conda_lockfile',
    version='0.1',
    packages=['conda_lockfile'],
    install_requires=['PyYAML'],
    setup_requires=['pytest-runner'],
    tests_require=['pytest'],
    entry_points={'console_scripts': ['conda-lockfile = conda_lockfile.cli:main']},
    include_package_data=True,
    package_dir={'mypkg': 'conda_lockfile'},
    package_data={'conda_lockfile': ['builder/Dockerfile', 'builder/build_lockfile.sh']},
)
