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


def compute_env_hash(f):
    return hashlib.sha1(f.read()).hexdigest()


def read_env_hash(f):
    for line in f:
        if line.startswith(ENVHASH_SIGIL):
            return line.split(ENVHASH_SIGIL)[1].strip()


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
    out = subprocess.check_output([CONDA, 'info', '--json'])
    out = json.loads(out)
    prefix = out['envs_dirs'][0]
    prefix = pathlib.Path(prefix)
    return prefix/name


def handle_create(args):
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
    with open(args.envfile, 'rb') as f:
        expected_hash = compute_env_hash(f)
        f.seek(0)
        env_name = yaml.load(f)['name']

    prefix = get_prefix(env_name)

    with open(prefix/'env.lock.yml') as f:
        found_hash = read_env_hash(f)

    if expected_hash != found_hash:
        raise Exception(f'Hash does not match: {expected_hash}, {found_hash}')


def handle_freeze(args):
    image_name = 'lock_file_maker'
    pkg_root = pathlib.Path(os.path.dirname(sys.modules['conda_lockfile'].__file__))
    dockerfile_path = pkg_root/'builder'
    subprocess.check_call(['docker', 'build', dockerfile_path, '-t', image_name])

    with open(args.envfile, 'rb') as f:
        env_hash = compute_env_hash(f)
        f.seek(0)
        env_name = yaml.load(f)['name']

    TMP_DIR = '/tmp/conda_lockfile'
    try:
        os.mkdir(TMP_DIR)
    except FileExistsError:
        pass

    with tempfile.TemporaryDirectory(dir=TMP_DIR) as tmp_dir:
        tmp_dir = pathlib.Path(tmp_dir)
        shutil.copyfile(args.envfile, tmp_dir/'env.yml')
        with open(tmp_dir/'env_name', 'w') as f:
            f.write(env_name)
        subprocess.check_call([
            'docker', 'run',
            '-v', f'{tmp_dir}:/app/artifacts',
            '-t', image_name,
        ])
        with open(args.lockfile, 'w') as lockfile, open(tmp_dir/'env.lock.yml') as tmp_env_file:
            lockfile.write(ENVHASH_SIGIL + env_hash + '\n')
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
