import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

ENVHASH_SIGIL = '# ENVHASH:'

CONDA = os.environ['CONDA_EXE']


def compute_env_hash_and_name(f):
    """Compute the hash of an env.yml file & extract the env's name.

    :rtype str env_hash: Hash of the environment
    :rtype str name: Name of the environment
    """
    env_hash = hashlib.sha1(f.read()).hexdigest()
    f.seek(0)
    env_name = yaml.load(f)['name']
    return env_hash, env_name


def read_env_hash(f):
    """Read the hash of an environment.

    :param file f: File object for the environment lockfile (ie env.yml.lock)
    :rtype str: the hash of the environment
    """
    for line in f:
        if line.startswith(ENVHASH_SIGIL):
            return line.split(ENVHASH_SIGIL)[1].strip()
    raise Exception('Did not find hash')


def find_file(name, starting_dir=pathlib.Path('.')):
    path = pathlib.Path(name)
    if path.exists():
        return path.resolve()

    starting_dir = pathlib.Path(starting_dir).resolve()
    if not starting_dir.is_dir():
        starting_dir = starting_dir.parent

    parents = [starting_dir] + list(starting_dir.parents)
    for parent in parents:
        maybe_file = parent/name
        if maybe_file.exists():
            return maybe_file
    raise Exception(f'{name} not found')


def get_prefix(name):
    """Get the directory where an environment is installed.

    :param str name: The name of the environment.
    :rtype: pathlib.Path
    """
    out = subprocess.check_output([CONDA, 'info', '--json'])
    out = json.loads(out)
    prefix = out['envs_dirs'][0]
    prefix = pathlib.Path(prefix)
    return prefix/name


def handle_create(args):
    """Create an environment from a env_file.

    The environments created contain the metadata to describe their provenance.
    """
    with open(args.lockfile) as f:
        data = yaml.load(f)
    name = data['name']
    subprocess.check_call([
        CONDA, 'env', 'create',
        '--force',
        '-q',
        '--json',
        '--name', name,
        '-f', args.lockfile,
    ])

    prefix = get_prefix(name)
    shutil.copyfile(args.lockfile, prefix/'env.lock.yml')


def handle_check(args):
    """Check that the installed environment's hash matches the specified requirements.

    This computes a hash of the env_file & compares that with a hash embedded in
    the constructed environment.
    """
    with open(args.envfile, 'rb') as f:
        expected_hash, env_name = compute_env_hash_and_name(f)

    prefix = get_prefix(env_name)

    with open(prefix/'env.lock.yml') as f:
        found_hash = read_env_hash(f)

    if expected_hash != found_hash:
        raise Exception(f'Hash does not match: {expected_hash}, {found_hash}')


def handle_freeze(args):
    """Freeze the requirements from an env file into a detailed lockfile.

    The lockfile will explicitly list all depdencenies needed to exactly
    re-create the environment.
    """
    # The only way to know what should be in an environment is to build it and document
    # what dependencies showed up.
    # We do this in a docker container to ensure isolation, and to allow us to build
    # work on mac.
    image_name = 'lock_file_maker'
    pkg_root = pathlib.Path(os.path.dirname(sys.modules['conda_lockfile'].__file__))
    subprocess.check_call(['docker', 'build', pkg_root/'builder', '-t', image_name])

    with open(args.envfile, 'rb') as f:
        env_hash, env_name = compute_env_hash_and_name(f)

    TMP_DIR = '/tmp/conda_lockfile'
    try:
        os.mkdir(TMP_DIR)
    except FileExistsError:
        pass

    # We use the filesystem to interact with our env-file builder container.
    # This is a little janky, but less painful than dealing with stdout from
    # the container directly. The docker-daemon must have permission to share
    # this directory with containers.
    # Make a temporary directory to work in.
    with tempfile.TemporaryDirectory(dir=TMP_DIR) as tmp_dir:
        tmp_dir = pathlib.Path(tmp_dir)
        # Copy the "source" env.yml file.
        shutil.copyfile(args.envfile, tmp_dir/'env.yml')
        # Write a file with the environment's name so that the lockfile builder
        # knows what to name the environment.
        with open(tmp_dir/'env_name', 'w') as f:
            f.write(env_name)
        subprocess.check_call([
            'docker', 'run',
            '-v', f'{tmp_dir}:/app/artifacts',
            '-t', image_name,
        ])
        with open(args.lockfile, 'w') as lockfile, open(tmp_dir/'env.lock.yml') as tmp_env_file:
            # Embed a hash of the source env file into the lockfile.
            lockfile.write(ENVHASH_SIGIL + env_hash + '\n')
            # Now write the contents of the lockfile.
            lockfile.write(tmp_env_file.read())


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()

    create = subparsers.add_parser('create')
    create.add_argument('--lockfile', default=pathlib.Path('env.yml.lock'), type=pathlib.Path)
    create.set_defaults(handler=handle_create)

    check = subparsers.add_parser('check')
    check.add_argument('--envfile', default=pathlib.Path('env.yml'), type=pathlib.Path)
    check.add_argument('--env', default=None, type=pathlib.Path)
    check.set_defaults(handler=handle_check)

    freeze = subparsers.add_parser('freeze')
    freeze.add_argument('--envfile', default=pathlib.Path('env.yml'), type=pathlib.Path)
    freeze.add_argument('--name', type=str)
    freeze.add_argument('--lockfile', default=pathlib.Path('env.yml.lock'), type=pathlib.Path)
    freeze.set_defaults(handler=handle_freeze)

    args = parser.parse_args()
    return args.handler(args)
