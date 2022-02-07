#!/bin/bash

set -e

export PATH="$HOME/miniconda/bin:$PATH"

cd recipe
CARGO_NET_GIT_FETCH_WITH_CLI=true conda build .
conda build . --output | xargs anaconda -t $ANACONDA_ORG_TOKEN upload

