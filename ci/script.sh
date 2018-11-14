#!/bin/bash 

cargo test

export PATH="$HOME/miniconda/bin:$PATH"
cd recipe
conda build .
conda build . --output
