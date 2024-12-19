#!/bin/bash

set -e

if [[ "$(uname)" == "Darwin" ]]; then
    URL="https://repo.anaconda.com/miniconda/Miniconda3-py39_24.11.1-0-MacOSX-arm64.sh"
    HOMEBREW_NO_AUTO_UPDATE=1 brew install wget
else
    URL="https://repo.anaconda.com/miniconda/Miniconda3-py39_24.11.1-0-Linux-x86_64.sh"
fi
wget $URL -O miniconda.sh;
bash miniconda.sh -b -p $HOME/miniconda
export PATH="$HOME/miniconda/bin:$PATH"
conda config --set always_yes yes --set changeps1 no
conda update -q conda

# Useful for debugging any issues with conda
conda info -a

conda install -q conda-build anaconda-client
