#!/bin/bash

set -e

export PATH="$HOME/miniconda/bin:$PATH"
export CARGO_NET_GIT_FETCH_WITH_CLI=true

cd recipe

conda build .
conda build . --output | xargs anaconda -t $ANACONDA_ORG_TOKEN upload

