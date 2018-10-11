"""conda lockfile manages the lifecycle of conda environments & dependencies.

1. Make a dependencies file `deps.yml`.  Only specify the dependencies you
specifically care about.  ex exclude transitive dependencies and versions you
don't care about.
2. `freeze` this to a `deps.yml.lock`.  The lockfile pins all dependencies
(including transitive dependencies) to the version & build number.
3. `create` the environment specified in the `deps.yml.lock`
4. `check` that the installed environment matches the one specified in $foo

conda lockfile is linux-centric.  The lockfile is generated to be
"""
import argparse
import hashlib
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable
from typing import Set
from typing import Tuple

import yaml

ENVHASH_SIGIL = '# ENVHASH:'

SUCCESS_CODE = 0
FAILURE_CODE = 1

SYSTEM = platform.system()


def check_output(cmd) -> bytes:
    print('running:', ' '.join(str(x) for x in cmd))
    try:
        return subprocess.check_output(cmd)
    except subprocess.CalledProcessError as e:
        print(e)
        print('[cmd]\n', e.cmd)
        print('')
        print('[returncode]\n', e.returncode)
        print('')
        print('[output]\n', e.output.decode('utf-8'))
        print('')
        print('[stdout]\n', e.stdout.decode('utf-8') if e.stdout else None)
        print('')
        print('[stderr]\n', e.stderr.decode('utf-8') if e.stderr else None)
        print('')
        raise


def find_conda() -> str:
    conda = os.environ.get('CONDA_EXE')
    if conda:
        return conda
    conda = os.environ.get('_CONDA_EXE')
    if conda:
        return conda

    raise Exception()


class MissingEnvHash(Exception):
    pass


def compute_env_hash(f) -> str:
    """Compute the hash of an deps.yml file & extract the env's name.

    :param bytes-mode-file f: deps.yml file object
    :rtype str env_hash: Hash of the environment
    :rtype str name: Name of the environment
    """
    return hashlib.sha1(f.read()).hexdigest()


def read_env_hash(f) -> str:
    """Read the hash of an environment.

    :param file f: File object for the environment lockfile (ie deps.yml.lock)
    :rtype str: the hash of the environment
    """
    for line in f:
        if line.strip().startswith(ENVHASH_SIGIL):
            return line.split(ENVHASH_SIGIL)[1].strip()
    raise MissingEnvHash('Did not find hash')


def _find_file(name: str, starting_dir=pathlib.Path('.')) -> pathlib.Path:
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


def get_prefix(name: str) -> pathlib.Path:
    """Get the directory where an environment is installed.

    :param str name: The name of the environment.
    :rtype: pathlib.Path
    """
    out = check_output([find_conda(), 'info', '--json'])
    data = json.loads(out)
    prefix = data['envs_dirs'][0]
    prefix = pathlib.Path(prefix)
    return prefix/name


def handle_create(args) -> int:
    """Create an environment from a env_file.

    The environments created contain the metadata to describe their provenance.
    """
    with open(args.lockfile) as f:
        data = yaml.load(f)
    name = data['name']
    check_output([
        find_conda(), 'env', 'create',
        '--force',
        '-q',
        '--json',
        '--name', name,
        '-f', args.lockfile,
    ])

    prefix = get_prefix(name)
    shutil.copyfile(args.lockfile, prefix/'deps.yml.lock')

    return SUCCESS_CODE


def handle_check(args) -> int:
    """Check that the installed environment's hash matches the specified requirements.

    This computes a hash of the env_file & compares that with a hash embedded in
    the constructed environment.
    """
    depsfile_path = args.depsfile
    with open(depsfile_path, 'rb') as depsfile:
        expected_hash = compute_env_hash(depsfile)
        depsfile.seek(0)
        env_name = yaml.load(depsfile.read().decode('utf-8'))['name']

    prefix = get_prefix(env_name)

    lockfile_path = prefix/'deps.yml.lock'
    with open(lockfile_path) as lockfile:
        try:
            found_hash = read_env_hash(lockfile)
        except MissingEnvHash:
            print(f'Unable to find hash in {lockfile_path}')
            return FAILURE_CODE

    if expected_hash != found_hash:
        print(f'deps file ({depsfile_path}) and environment ({lockfile_path}) do not match:')
        print(f'expected: {expected_hash}')
        print(f'found:    {found_hash}')
        return FAILURE_CODE

    return SUCCESS_CODE


def handle_freeze(args) -> int:
    """Freeze the requirements from a deps file into a detailed lockfile.

    The lockfile will explicitly list all depdencenies needed to exactly
    re-create the environment.
    """
    if args.platform != SYSTEM:
        if SYSTEM == 'Darwin' and args.platform == 'Linux':
            return _linux_on_mac_freeze(args)
        print('Cross-platform build requested')
        print('The only supported cross platform build is `--platform=Linux` on Darwin')
        print(f'--platform={args.platform} on {SYSTEM} was requested')

        return FAILURE_CODE

    return _same_platform_freeze(args)


def _same_platform_freeze(args) -> int:
    tmp_env_name = '___conda_lockfile_temp'
    # Use a novel env name to avoid clobbering an env that already exists
    # TODO: Write a context manger to get a unique name & make sure it is
    # deleted when done.
    with open(args.depsfile, 'rb') as depsfile:
        env_hash = compute_env_hash(depsfile)
        depsfile.seek(0)
        env_name = yaml.load(depsfile.read().decode('utf-8'))['name']

    check_output(['conda', 'env', 'create', '-f', args.depsfile, '-n', tmp_env_name, '--force'])
    lock_yaml = check_output(['conda', 'env', 'export', '-n', tmp_env_name]).decode('utf-8')
    lock_data = yaml.load(lock_yaml)
    # Replace the temporary name with the real name.
    lock_data['name'] = env_name
    del lock_data['prefix']

    data = yaml.dump(lock_data)
    write_lockfile(data, env_hash, args.lockfile)

    return SUCCESS_CODE


def _linux_on_mac_freeze(args) -> int:
    # The only way to know what should be in an environment is to build it and document
    # what dependencies showed up.
    # We do this in a docker container to ensure isolation, and to allow us to build
    # work on mac.
    image_name = 'lock_file_maker'
    pkg_root = pathlib.Path(os.path.dirname(sys.modules['conda_lockfile'].__file__))
    print('Creating docker builder image')
    check_output(['docker', 'build', pkg_root/'builder', '-t', image_name])

    with open(args.depsfile, 'rb') as depsfile:
        env_hash = compute_env_hash(depsfile)
        depsfile.seek(0)
        env_name = yaml.load(depsfile.read().decode('utf-8'))['name']

    TMP_DIR = '/tmp/conda_lockfile'
    try:
        os.mkdir(TMP_DIR)
    except FileExistsError:
        pass

    # We use the filesystem to interact with our deps-file builder container.
    # This is a little janky, but less painful than dealing with stdout from
    # the container directly. The docker-daemon must have permission to share
    # this directory with containers.
    # Make a temporary directory to work in.
    with tempfile.TemporaryDirectory(dir=TMP_DIR) as td:
        tmp_dir = pathlib.Path(td)
        # Copy the "source" deps.yml file.
        shutil.copyfile(args.depsfile, tmp_dir/'deps.yml')
        # Write a file with the environment's name so that the lockfile builder
        # knows what to name the environment.
        with open(tmp_dir/'env_name', 'w') as env_name_file:
            env_name_file.write(env_name)
        print('Building environment')
        check_output([
            'docker', 'run',
            '-v', f'{tmp_dir}:/app/artifacts',
            '-t', image_name,
        ])

        # I've seen weird errors where the pip dependencies are excluded.  Make
        # sure the lockfile is not horribly broken.
        is_success = lockfile_is_depsfile_superset(tmp_dir/'deps.yml', tmp_dir/'deps.yml.lock')
        if not is_success:
            return FAILURE_CODE

        with open(tmp_dir/'deps.yml.lock') as tmp_env_file:
            data = tmp_env_file.read()
        write_lockfile(data, env_hash, args.lockfile)

    return SUCCESS_CODE


def write_lockfile(data: str, env_hash: str, lockfile_path: pathlib.Path) -> None:
    print('Writing lockfile')
    with open(lockfile_path, 'w') as lockfile:
        # Embed a hash of the source deps file into the lockfile.
        lockfile.write(ENVHASH_SIGIL + env_hash + '\n')
        # Now write the contents of the lockfile.
        lockfile.write(data)


def get_deps(deps: list) -> Tuple[Set[str], Set[str]]:
    """Extra conda/pip dependecies from environmentfile data

    Args:
        deps: data from environment.yml file
    Returns:
        conda_dependencies
        pip_dependencies
    """
    pip_deps: Set[str] = set()
    conda_deps = deps[:]
    for d in conda_deps[:]:
        if isinstance(d, dict):
            pip_deps.update(d['pip'])
            conda_deps.remove(d)
    return only_pkg_name(conda_deps), only_pkg_name(pip_deps)


def only_pkg_name(seq: Iterable[str]) -> Set[str]:
    """Strip out everything but package name from dependencies"""
    return {x.split('=')[0] for x in seq}


def lockfile_is_depsfile_superset(deps_path: pathlib.Path, lock_path: pathlib.Path):
    """Are the lockfile dependencies a superset of what is requested in the depsfile?

    They ought be.

    Args:
        deps_path: path to deps.yml
        lock_path: path to deps.yml.lock
    Returns:
        bool
    """
    with open(deps_path) as f:
        spec = yaml.load(f)
    with open(lock_path) as f:
        lock = yaml.load(f)
    conda_spec, pip_spec = get_deps(spec['dependencies'])
    conda_lock, pip_lock = get_deps(lock['dependencies'])
    return conda_lock.issuperset(conda_spec) and pip_lock.issuperset(pip_spec)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers()

    create = subparsers.add_parser('create', help=handle_create.__doc__)
    create.add_argument('--lockfile', default=None, type=pathlib.Path)
    create.set_defaults(handler=handle_create)

    check = subparsers.add_parser('check', help=handle_check.__doc__)
    check.add_argument('--depsfile', default=pathlib.Path('deps.yml'), type=pathlib.Path)
    check.set_defaults(handler=handle_check)

    freeze = subparsers.add_parser('freeze', help=handle_freeze.__doc__)
    freeze.add_argument('--depsfile', default=pathlib.Path('deps.yml'), type=pathlib.Path)
    freeze.add_argument('--lockfile', default=None, type=pathlib.Path)
    freeze.add_argument('--platform', default=SYSTEM, type=str, choices=['Darwin', 'Linux'])
    freeze.set_defaults(handler=handle_freeze)

    args = parser.parse_args()
    # We want the default values of lockfile to depend on --platform.
    # So re-compute the name after we're done parsing.
    if hasattr(args, 'lockfile') and args.lockfile is None:
        args.lockfile = pathlib.Path(f'deps.yml.{args.platform}.lock')
    return_code = args.handler(args)
    sys.exit(return_code)


if __name__ == '__main__':
    main()
