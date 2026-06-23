FROM docker.io/debian:13 AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON=python3.14 \
    UV_PROJECT_ENVIRONMENT=/app \
    UV_PYTHON_INSTALL_DIR=/usr/share/uv/python

WORKDIR /build

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --locked \
    --no-dev \
    --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --locked \
    --no-dev \
    --no-editable

FROM gcr.io/distroless/cc-debian13:nonroot
COPY --from=build /usr/share/uv /usr/share/uv
COPY --from=build --chown=nonroot:nonroot /app /app
COPY --from=build /build/pyproject.toml /pyproject.toml
ENV PATH=/app/bin:$PATH
CMD ["/app/bin/brewery-server"]
