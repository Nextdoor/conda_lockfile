#!/bin/bash

set -e

export PATH="$HOME/miniconda/bin:$PATH"

cd recipe
conda build .
conda build . --output | xargs anaconda -t $ANACONDA_ORG_TOKEN upload

