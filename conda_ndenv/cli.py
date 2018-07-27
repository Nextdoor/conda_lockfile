import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import tempfile

import docker
import yaml

ENVHASH_SIGIL = '# ENVHASH:'


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
    out = subprocess.check_outputx(['conda', 'info', '--json'])
    out = json.loads(out)
    prefix = out['envs_dirs'][0]
    prefix = pathlib.Path(prefix)
    return prefix/name


def add_create(subparsers):
    parser = subparsers.add_parser('create')
    parser.add_argument('--lockfile', default=pathlib.Path('env.lock.yml'), type=find_file)
    return handle_create


def handle_create(parser):
    if parser.name is None:
        data = yaml.load(parser.lockfile)
        name = data['name']
    subprocess.check_call([
        'conda', 'env', 'create',
        '--force',
        '-q',
        '--json',
        '--name', name,
        '-f', parser.lockfile,
    ])

    prefix = get_prefix(name)
    shutil.copyfile(parser.lockfile, prefix/'env.lock.yml')


def add_check(subparsers):
    parser = subparsers.add_parser('check')
    parser.add_argument('--envfile', default=pathlib.Path('env.yml'), type=find_file)
    parser.add_argument('--env', default=None, type=pathlib.Path)
    return handle_check


def handle_check(parser):
    with open(parser.envfile, 'rb') as f:
        expected_hash = compute_env_hash(f)
        f.seek(0)

    env_name = yaml.load(parser.envfile)['name']
    prefix = get_prefix(env_name)

    with open(prefix/'env.lock.yml') as f:
        found_hash = read_env_hash(f)

    if expected_hash != found_hash:
        raise Exception('Hash does not match')


def add_freeze(subparsers):
    parser = subparsers.add_parser('freeze')
    parser.add_argument('--envfile', default=pathlib.Path('env.yml'), type=find_file)
    parser.add_argument('--name', type=str)
    parser.add_argument('--lockfile', default=pathlib.Path('env.yml.lock'), type=find_file)
    return handle_freeze


def handle_freeze(parser):
    client = docker.from_env()
    client.image.create(path='~/src/nextdoor.com/conda_lockfile/Dockerfile', tag='lock_file_maker')

    with open(parser.envfile, 'rb') as f:
        env_hash = compute_env_hash(f)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir = pathlib.Path(tmp_dir)
        shutil.copyfile(parser.envfile, tmp_dir/'env.yml')
        with open(tmp_dir/'env_name', 'w') as f:
            f.write(parser.name)
        client.containers.run('lock_file_maker')
        with open(parser.lockfile, 'w') as lockfile:
            lockfile.write(ENVHASH_SIGIL + env_hash + '\n')
        shutil.copyfile(tmp_dir/'env.lock.yml', parser.lockfile)


def main():
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers()
    handlers = {
        'create': add_create(subparsers),
        'check': add_check(subparsers),
        'freeze': add_freeze(subparsers),
    }

    parser.parse_args()
    handler = handlers[parser.subparser_name]
    return handler(parser)
