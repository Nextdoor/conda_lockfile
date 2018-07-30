#! /bin/bash

set -e

cd artifacts

# We need the name of the environment for exporting the environment.
# Unfortunately, `conda env create` doesn't return any information identifying
# the name of the environment it created. As a workaround, provide an explicit
# name to `conda env create` so there is no ambiguity when calling `conda env
# export`.  This name *ought* be what is specified in `env.yml` itself.
ENV_NAME=$(cat env_name)
$CONDA_ROOT/bin/conda env create -f env.yml -n $ENV_NAME env.yml
# The prefix line includes an absolute path from inside this container.
# Remove it to avoid confusion.
$CONDA_ROOT/bin/conda env export -n $ENV_NAME | grep -v "^prefix:" > env.lock.yml
