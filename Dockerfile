# SPDX-License-Identifier: Apache-2.0
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv-tools
FROM ubuntu:24.04@sha256:24737cef17f4e22b1977df7d9a05e77c4e28b7da5b8911f8d8ccda136bf3573c AS development
COPY --from=uv-tools /uv /uvx /usr/local/bin/
COPY tools/gazebo.gpg /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg
COPY tools/ubuntu-packages.lock /tmp/ubuntu-packages.lock
RUN --mount=type=secret,id=ca,required=false,mode=0444 set -eu; \
    chmod 644 /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg; \
    if [ -f /run/secrets/ca ]; then sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources; export SSL_CERT_FILE=/run/secrets/ca; fi; \
    apt-get -o Acquire::https::CaInfo="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" update; \
    DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::https::CaInfo="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" install -y ca-certificates=20260816ubuntu0.24.04.1 curl=8.5.0-2ubuntu10.16; \
    echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] https://packages.osrfoundation.org/gazebo/ubuntu-stable noble main' > /etc/apt/sources.list.d/gazebo-stable.list; \
    apt-get -o Acquire::https::CaInfo="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" update; \
    DEBIAN_FRONTEND=noninteractive xargs -a /tmp/ubuntu-packages.lock apt-get -o Acquire::https::CaInfo="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" install -y; \
    rm -rf /var/lib/apt/lists/*
ARG TASK_VERSION=3.54.0
RUN --mount=type=secret,id=ca,required=false,mode=0444 set -eu; \
    if [ -f /run/secrets/ca ]; then export CURL_CA_BUNDLE=/run/secrets/ca; fi; \
    arch="$(dpkg --print-architecture)"; mkdir /tmp/task; cd /tmp/task; \
    curl --connect-timeout 15 --max-time 120 -fsSLO "https://github.com/go-task/task/releases/download/v${TASK_VERSION}/task_linux_${arch}.tar.gz"; \
    curl --connect-timeout 15 --max-time 120 -fsSLO "https://github.com/go-task/task/releases/download/v${TASK_VERSION}/task_checksums.txt"; \
    sha256sum --ignore-missing -c task_checksums.txt; tar -xzf "task_linux_${arch}.tar.gz" task; install task /usr/local/bin/task; rm -rf /tmp/task
ENV LIVINGPROOF_TOOLING=1 UV_PROJECT_ENVIRONMENT=/opt/gazebo-venv UV_CACHE_DIR=/opt/gazebo-cache UV_SYSTEM_CERTS=true UV_PYTHON_DOWNLOADS=never
RUN mkdir /opt/gazebo-venv /opt/gazebo-cache && chmod 1777 /opt/gazebo-venv /opt/gazebo-cache && groupmod --new-name vscode ubuntu && usermod --login vscode --home /home/vscode --move-home ubuntu
WORKDIR /workspace/gazebo
CMD ["sleep", "infinity"]
# Git is required for build provenance and development tasks.
RUN --mount=type=secret,id=ca,required=false,mode=0444 set -eu; \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    apt-get -o Acquire::https::CaInfo="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" update; \
    DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::https::CaInfo="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" install -y --no-install-recommends git=1:2.43.0-1ubuntu7.4 git-man=1:2.43.0-1ubuntu7.4 liberror-perl=0.17029-2; \
    rm -rf /var/lib/apt/lists/*
