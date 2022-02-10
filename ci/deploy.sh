#!/bin/bash

set -e

export PATH="$HOME/miniconda/bin:$PATH"
export CARGO_NET_GIT_FETCH_WITH_CLI=true

echo "[url \"https://github.com/rust-lang/crates.io-index\"]" >> ~/.gitconfig
echo "        insteadOf = https://github.com/rust-lang/crates.io-index" >> ~/.gitconfig

cd recipe

conda build .
conda build . --output | xargs anaconda -t $ANACONDA_ORG_TOKEN upload

