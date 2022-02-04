#!/bin/bash 

set -e

curl https://sh.rustup.rs -sSf | sh -s -- -y
export PATH="$HOME/.cargo/bin:$PATH"

eval `ssh-agent -s`
ssh-add

cargo test

export PATH="$HOME/miniconda/bin:$PATH"
cd recipe
conda build .
conda build . --output
