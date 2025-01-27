FROM python:3.13-slim-bookworm AS builder

RUN apt -y update \
    && apt install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd
RUN useradd --system --create-home --shell /bin/bash --gid bot bot
RUN chown -R bot:bot /home/bot/

USER bot
WORKDIR /home/bot/

RUN mkdir -p /home/bot/.local/bin/
ENV PATH="$PATH:/home/bot/.local/bin/"

COPY --chown=bot:bot .git/ ./.git/
COPY --chown=bot:bot bobuild/ ./bobuild/
COPY --chown=bot:bot .gitmodules .
COPY --chown=bot:bot pyproject.toml .
COPY --chown=bot:bot README.md .

RUN pip install --upgrade pip --no-cache-dir \
    && pip install --no-cache-dir \
    hatch \
    .

RUN hatch build --target wheel
