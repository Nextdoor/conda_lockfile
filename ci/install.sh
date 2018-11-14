#!/bin/bash

if [[ "$(uname)" == "Darwin" ]]; then
    URL="https://repo.continuum.io/miniconda/Miniconda3-latest-MacOSX-x86_64.sh"
else
    URL="https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh"
fi
wget $URL -O miniconda.sh;
bash miniconda.sh -b -p $HOME/miniconda
export PATH="$HOME/miniconda/bin:$PATH"
conda config --set always_yes yes --set changeps1 no
conda update -q conda
# Useful for debugging any issues with conda
conda info -a

conda install -q conda-build anaconda-client
