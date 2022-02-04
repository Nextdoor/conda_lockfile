#!/bin/bash

set -e

if [[ "$(uname)" == "Darwin" ]]; then
    URL="https://repo.anaconda.com/miniconda/Miniconda3-py37_4.8.2-MacOSX-x86_64.sh"
else
    URL="https://repo.anaconda.com/miniconda/Miniconda3-py37_4.8.2-Linux-x86_64.sh"
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

# `conda update -q conda` removes libffi.6.dylib and replaces it with libffi.7.dylib and libffi.8.dylib
# libffi.6.dylib is required for `conda install`. https://github.com/conda/conda/issues/9038.
ln -s $HOME/miniconda/lib/libffi.7.dylib $HOME/miniconda/lib/libffi.6.dylib

# Useful for debugging any issues with conda
conda info -a

conda install -q conda-build anaconda-client
