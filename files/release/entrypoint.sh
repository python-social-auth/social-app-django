#!/usr/bin/env bash

set -e

if [ -z "${PYPI_USERNAME}" ] || [ -z "${PYPI_PASSWORD}" ]; then
    echo "====================================================================="
    echo "Error: missing PYPI_USERNAME or PYPI_PASSWORD environment values"
    echo "====================================================================="
    exit 1;
fi

if [ -z "${PROJECT_DIR}" ] || [ -z "${PROJECT_NAME}" ]; then
    echo "====================================================================="
    echo "Error: missing PROJECT_DIR or PROJECT_NAME environment values"
    echo "====================================================================="
    exit 1;
fi

envsubst < /pypirc.template > ~/.pypirc

# This will fail if tag doesn't exist
CURRENT_VERSION=$(head -n1 ${PROJECT_DIR}/__init__.py | awk '{print $3}' | sed 's/[^0-9\.]//g')
CURRENT_TAG=$(git describe --tags --abbrev=0)

if [ "${CURRENT_VERSION}" != "${CURRENT_TAG}" ]; then
    echo "====================================================================="
    echo "Error: version '${CURRENT_VERSION}' not tagged"
    echo "====================================================================="
    exit 1;
fi

PYPI_URL="https://pypi.org/project/${PROJECT_NAME}/${CURRENT_VERSION}/"
VERSION_PAGE_STATUS=$(curl -s -I ${PYPI_URL} | head -n1 | awk '{print $2}')

if [ "${VERSION_PAGE_STATUS}" == "200" ]; then
    echo "====================================================================="
    echo "Error: version '${CURRENT_VERSION}' already exists"
    echo "====================================================================="
    exit 1;
fi

make clean build publish
