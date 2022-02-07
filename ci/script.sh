#!/bin/bash 

set -e

curl https://sh.rustup.rs -sSf | sh -s -- -y
export PATH="$HOME/.cargo/bin:$PATH"

export CARGO_NET_GIT_FETCH_WITH_CLI=true
CARGO_NET_GIT_FETCH_WITH_CLI=true cargo test

eval `ssh-agent -s`
ssh-add

export PATH="$HOME/miniconda/bin:$PATH"
cd recipe
CARGO_NET_GIT_FETCH_WITH_CLI=true conda build .
conda build . --output
