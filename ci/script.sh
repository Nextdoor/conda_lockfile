#!/bin/bash 

set -e

curl https://sh.rustup.rs -sSf | sh -s -- -y
export PATH="$HOME/.cargo/bin:$PATH"
export CARGO_NET_GIT_FETCH_WITH_CLI=true

echo "[url \"https://github.com/rust-lang/crates.io-index\"]" >> ~/.gitconfig
echo "        insteadOf = https://github.com/rust-lang/crates.io-index" >> ~/.gitconfig

cargo test

export PATH="$HOME/miniconda/bin:$PATH"
cd recipe
conda build .
conda build . --output
