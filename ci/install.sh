#!/bin/bash

set -e

if [[ "$(uname)" == "Darwin" ]]; then
    URL="https://repo.anaconda.com/miniconda/Miniconda3-py37_4.10.3-MacOSX-x86_64.sh"
else
    URL="https://repo.anaconda.com/miniconda/Miniconda3-py37_4.10.3-Linux-x86_64.sh"
fi
wget $URL -O miniconda.sh;
bash miniconda.sh -b -p $HOME/miniconda
export PATH="$HOME/miniconda/bin:$PATH"
echo "here conda config"
ls $HOME/miniconda/lib/
conda config --set always_yes yes --set changeps1 no
echo "here conda update"
ls $HOME/miniconda/lib/
conda update -q conda

echo "after conda update"
ls $HOME/miniconda/lib/

# Useful for debugging any issues with conda
conda info -a

conda install -q conda-build anaconda-client
