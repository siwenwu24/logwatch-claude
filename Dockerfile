# syntax=docker/dockerfile:1

# ---- build stage -------------------------------------------------------
# Installing into a throwaway prefix keeps build tooling and caches out of
# the final image.
FROM python:3.13-slim AS builder

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --prefix=/install .

# ---- runtime stage -----------------------------------------------------
FROM python:3.13-slim

LABEL org.opencontainers.image.title="logwatch" \
      org.opencontainers.image.description="Watch a directory of .log files and report on levels and keywords." \
      org.opencontainers.image.source="https://github.com/siwenwu24/logwatch-claude" \
      org.opencontainers.image.licenses="MIT"

# Unbuffered output so `docker logs` shows reports as they are produced.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /install /usr/local

# Run as an unprivileged user; it only ever needs to read the mounted logs.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin logwatch \
    && mkdir -p /logs \
    && chown logwatch:logwatch /logs

USER logwatch
WORKDIR /home/logwatch

# Mount the host's log directory here:
#   docker run -v /path/to/logs:/logs:ro ghcr.io/siwenwu24/logwatch-claude
VOLUME ["/logs"]

ENTRYPOINT ["logwatch"]
CMD ["watch", "--dir", "/logs"]
