FROM python:3.13-slim-bookworm AS builder

RUN apt -y update \
    && apt install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd scheduler
RUN useradd --system --create-home --shell /bin/bash --gid scheduler scheduler
RUN chown -R scheduler:scheduler /home/scheduler/

USER scheduler
WORKDIR /home/scheduler/

RUN mkdir -p /home/scheduler/.local/bin/
ENV PATH="$PATH:/home/scheduler/.local/bin/"

COPY --chown=scheduler:scheduler .git/ ./.git/
COPY --chown=scheduler:scheduler bobuild/ ./bobuild/
COPY --chown=scheduler:scheduler .gitmodules .
COPY --chown=scheduler:scheduler pyproject.toml .
COPY --chown=scheduler:scheduler README.md .
COPY --chown=scheduler:scheduler submodules/ ./submodules/

RUN pip install --upgrade pip --no-cache-dir \
    && pip install --no-cache-dir \
    hatch \
    .

RUN hatch build --target wheel

FROM python:3.13-slim-bookworm

RUN apt -y update \
    && apt install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd scheduler
RUN useradd --system --create-home --shell /bin/bash --gid scheduler scheduler
RUN chown -R scheduler:scheduler /home/scheduler/

USER scheduler
WORKDIR /home/scheduler/

COPY --from=builder --chown=scheduler:scheduler /home/scheduler/dist/ ./dist/

RUN ls -lah /home/scheduler/dist/

RUN pip install --upgrade pip --no-cache-dir \
    && pip install --no-cache-dir \
    /home/scheduler/dist/bobuild*.whl \
    --target /home/scheduler/bobuild/

ENV PATH="$PATH:/home/scheduler/.local/bin/"

CMD ["taskiq", "scheduler", "bobuild.tasks:scheduler", \
    "--tasks-pattern", "bobuild/**/tasks*.py", "--fs-discover"]
