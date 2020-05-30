#!/usr/bin/env bash

set -e

export PATH=~/.pyenv/shims:~/.pyenv/bin:${PATH}
export PYENV_ROOT=~/.pyenv
export PYTHON_VERSIONS=${PYTHON_VERSIONS}

curl -L https://raw.githubusercontent.com/yyuu/pyenv-installer/master/bin/pyenv-installer | bash

eval "$(pyenv init -)"

for version in ${PYTHON_VERSIONS}; do
    pyenv install "${version}"
    pyenv local "${version}"
    pip install --upgrade setuptools pip tox
    pyenv local --unset
done

pyenv local ${PYTHON_VERSIONS}
