FROM debian:bookworm-slim AS builder

ARG ACTIONS_CACHE_URL=""
ARG VCPKG_BINARY_SOURCES=""
ARG CONFIGURE_TARGET="config-linux-release-x64-gcc"
ARG BUILD_TARGET="linux-release-x64-gcc"
ARG CMAKE_SHA256="84791d2675054aa167f14008ba3e41dd599d695c0a8fcc7eb8bcf50006d33938"

COPY ./docker/apt_lists/stable.list /etc/apt/sources.list.d/stable.list
COPY ./docker/apt_lists/testing.list /etc/apt/sources.list.d/testing.list

RUN echo "APT::Default-Release "stable";" >> /etc/apt/apt.conf.d/99defaultrelease \
    && apt -y update \
    && apt install -y --no-install-recommends -t testing \
    build-essential \
    gcc-14 \
    mold \
    ninja-build \
    && apt install -y --no-install-recommends \
    autoconf \
    bison \
    ca-certificates \
    curl \
    flex \
    git \
    libssl-dev \
    make \
    pkg-config \
    tar \
    unzip \
    wget \
    zip \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN export CMAKE_MAKE_PROGRAM=make \
    && wget https://github.com/Kitware/CMake/releases/download/v3.31.4/cmake-3.31.4-linux-x86_64.sh \
    -O cmake.sh \
    && echo "${CMAKE_SHA256} ./cmake.sh" | sha256sum --check --status \
    && /bin/sh ./cmake.sh --skip-license --prefix=/usr/local

RUN groupadd bot
RUN useradd --system --create-home --shell /bin/bash --gid bot bot
RUN chown -R bot:bot /home/bot/

USER bot
WORKDIR /home/bot/

COPY --chown=bot:bot .git/ .git/
COPY --chown=bot:bot .gitmodules .
COPY --chown=bot:bot README.md .
COPY --chown=bot:bot build_commands_bot/cmake/ ./build_commands_bot/cmake/
COPY --chown=bot:bot build_commands_bot/src/ ./build_commands_bot/src/
COPY --chown=bot:bot build_commands_bot/include/ ./build_commands_bot/include/
COPY --chown=bot:bot build_commands_bot/submodules/ ./build_commands_bot/submodules/
COPY --chown=bot:bot build_commands_bot/CMakeLists.txt ./build_commands_bot/CMakeLists.txt
COPY --chown=bot:bot build_commands_bot/CMakePresets.json ./build_commands_bot/CMakePresets.json
COPY --chown=bot:bot build_commands_bot/vcpkg.json ./build_commands_bot/vcpkg.json

RUN --mount=type=secret,id=ACTIONS_RUNTIME_TOKEN,env=ACTIONS_RUNTIME_TOKEN \
    bash ./build_commands_bot/submodules/vcpkg/bootstrap-vcpkg.sh -disableMetrics

WORKDIR /home/bot/build_commands_bot/

RUN --mount=type=secret,id=ACTIONS_RUNTIME_TOKEN,env=ACTIONS_RUNTIME_TOKEN \
    cmake --preset $CONFIGURE_TARGET \
    && cmake --build --preset $BUILD_TARGET

FROM debian:bookworm-slim

ARG CONFIGURE_TARGET="config-linux-release-x64-gcc"

RUN groupadd bot
RUN useradd --system --create-home --shell /bin/bash --gid bot bot
RUN chown -R bot:bot /home/bot/

COPY ./docker/apt_lists/stable.list /etc/apt/sources.list.d/stable.list
COPY ./docker/apt_lists/testing.list /etc/apt/sources.list.d/testing.list

RUN echo "APT::Default-Release "stable";" >> /etc/apt/apt.conf.d/99defaultrelease \
    && apt -y update \
    && apt install -y --no-install-recommends -t testing \
    libc6 \
    libssl-dev \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

USER bot
WORKDIR /home/bot/

COPY --from=builder --chown=bot:bot \
    /home/bot/build_commands_bot/cmake-build-$CONFIGURE_TARGET/src/build_commands_bot \
    /home/bot/build_commands_bot

COPY --from=builder --chown=bot:bot \
    /home/bot/build_commands_bot/cmake-build-$CONFIGURE_TARGET/submodules/dpp/**/*.so* \
    /home/bot/

COPY --from=builder --chown=bot:bot \
    /home/bot/build_commands_bot/cmake-build-$CONFIGURE_TARGET/vcpkg_installed/x64-*/lib/**/*.a* \
    /home/bot/

COPY --chown=bot:bot ./docker/build_commands_bot.sh .

ENTRYPOINT ["./build_commands_bot.sh"]
