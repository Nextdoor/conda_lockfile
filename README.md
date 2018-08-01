[![CircleCI](https://circleci.com/gh/Nextdoor/conda_lockfile.svg?style=svg)](https://circleci.com/gh/Nextdoor/conda_lockfile)

conda_lockfile
==============

`conda_lockfile` manages the life cycle of a production conda environment.

The intention is to allow developers to manage their requirements at a
relatively high level, while also being able to repeatably deploy the exact
same environment.

`deps.yml`
-----------------------
The cycle starts with a deps.yml file (a conda environment file) that specifies
the application environment's dependencies.  This should be as loose as
possible and only specified the packages and versions that you specifically
want to manage.  The standard name for this file is `deps.yml`

`conda lockfile freeze`
-----------------------
From this high level description of dependencies, `conda_lockfile` will
generate a detailed, comprehensive list of dependencies.  ie a lockfile.  This
file is immune to dependencies publishing updated versions.  So long as your
project uses this lockfile the environment will be exactly the same.  The
standard name for this file is `deps.yml.lock.  This file will generally be
checked into source control.

`conda lockfile create`
-----------------------
From the lockfile, `conda_lockfile` can create an environment. This is a
thin wrapper around `conda env create` plus some additional metadata
to verify the provenance of the lockfile/environment.

`conda lockfile check`
----------------------
Verifies that `deps.yml` and installed environment "match".  It does this by
embedding a hash of `deps.yml` and stashing that within the environment created
from `deps.yml.lock`.  This is primarily useful for development & quickly
detecting changes to `deps.yml` that invalidate the existing environment.
