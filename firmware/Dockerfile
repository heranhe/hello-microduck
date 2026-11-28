FROM rust:1-bookworm
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get -o Acquire::Retries=4 update && apt-get -o Acquire::Retries=4 install -y --no-install-recommends \
    python3 xz-utils util-linux e2fsprogs parted curl ca-certificates \
    pkg-config libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    libgstreamer-plugins-bad1.0-dev gstreamer1.0-tools \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad
WORKDIR /src
