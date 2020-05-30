FROM python:3.8.2-slim-buster

ARG PYTHON_VERSIONS=${PYTHON_VERSIONS}
ENV PYTHON_VERSIONS=${PYTHON_VERSIONS}

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        make git pkg-config ca-certificates wget curl llvm build-essential \
        python-openssl libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
        libsqlite3-dev libncurses5-dev libncursesw5-dev xz-utils libxml2-dev \
        libxmlsec1-dev libffi-dev tk-dev liblzma-dev

COPY ./files/tests/pyenv.sh /
RUN /pyenv.sh

COPY ./files/tests/entrypoint.sh /

ADD . /code

WORKDIR /code

ENTRYPOINT ["/entrypoint.sh"]
