import io

import pytest

from . import cli


def test_compute_env_hash_and_name():
    f = io.BytesIO(
        b"""
        # name: not-test
        name: test
        channels:
        - conda-forge
        dependencies:
        - python=3.6
        """)
    env_hash, name = cli.compute_env_hash_and_name(f)
    assert name == 'test'
    assert env_hash == 'd43c75e901a38edc8f01913b41bb3f757347a9b9'


def test_read_env_hash():
    f = io.StringIO(
        """
        # ENVHASH: abcd
        name: test
        channels:
        - conda-forge
        dependencies:
        - python=3.6
        """)
    env_hash = cli.read_env_hash(f)
    assert env_hash == 'abcd'


def test_read_env_hash_missing_hash():
    f = io.StringIO(
        """
        name: test
        channels:
        - conda-forge
        dependencies:
        - python=3.6
        """)
    with pytest.raises(cli.MissingEnvHash):
        cli.read_env_hash(f)
