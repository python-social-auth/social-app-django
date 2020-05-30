#!/usr/bin/env bash

set -e

export PATH=~/.pyenv/shims:~/.pyenv/bin:${PATH}
export PYENV_ROOT=~/.pyenv

eval "$(pyenv init -)"

tox
