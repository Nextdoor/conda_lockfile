#!/bin/bash

set -e

if [[ "$(uname)" == "Darwin" ]]; then
    URL="https://repo.anaconda.com/miniconda/Miniconda3-py37_4.8.2-MacOSX-x86_64.sh"
    brew install libffi
else
    URL="https://repo.anaconda.com/miniconda/Miniconda3-py37_4.8.2-Linux-x86_64.sh"
fi
wget $URL -O miniconda.sh;
bash miniconda.sh -b -p $HOME/miniconda
ls $HOME/miniconda/lib/
export PATH="$HOME/miniconda/bin:$PATH"
conda config --set always_yes yes --set changeps1 no
conda update -q conda
# Useful for debugging any issues with conda
conda info -a

conda install -q conda-build anaconda-client
