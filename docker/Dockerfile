# syntax=docker/dockerfile:1
# Multi-stage build for the Python backend (api / bot / worker share one image).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# --- deps layer ---
FROM base AS deps
COPY requirements.txt ./
RUN pip install -r requirements.txt

# --- runtime ---
FROM base AS runtime
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY . .

# Entrypoint: copied as root and made executable (the repo file may not carry
# the +x bit, e.g. checked out on a Windows/DrvFS mount).
RUN cp docker/entrypoint.sh /usr/local/bin/entrypoint.sh \
 && chmod 0755 /usr/local/bin/entrypoint.sh

# Non-root runtime user.
RUN useradd --system --uid 1001 --home /app appuser \
 && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["api"]
