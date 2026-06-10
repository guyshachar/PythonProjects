# ── ScoutCut container image ──────────────────────────────────────────────────
#
# Includes:
#   • ffmpeg + ffprobe   (system package)
#   • scoutCut runtime   (yt-dlp, Pillow, google-api-*)
#   • Playwright + Chromium browser (pixellot_scraper, veo_scraper)
#   • FastAPI / Celery web layer
#
# Build:   docker build -t scoutcut .
# Run:     docker compose up

FROM python:3.11-slim

# ── System packages ───────────────────────────────────────────────────────────
# ffmpeg  : video processing (includes ffprobe)
# curl    : healthchecks, yt-dlp internal use
# ca-certificates : TLS for Playwright browser download
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      curl \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python layer 1: scoutCut runtime ─────────────────────────────────────────
# Copied before source so this layer is cached as long as requirements.txt
# doesn't change — even when scoutCut.py or the web layer changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Playwright Chromium browser ───────────────────────────────────────────────
# --with-deps  : auto-installs all required system libraries for Chromium
#               (libnss3, libatk*, libgbm, etc.) via apt
# The browser is stored at /root/.cache/ms-playwright/ inside the image.
RUN playwright install chromium --with-deps

# ── Python layer 2: web application ─────────────────────────────────────────
COPY web/requirements.txt /tmp/web-requirements.txt
RUN pip install --no-cache-dir -r /tmp/web-requirements.txt

# ── Application source ───────────────────────────────────────────────────────
# Copied last — source changes don't invalidate the browser/deps layers.
COPY . .

# ── Runtime defaults ─────────────────────────────────────────────────────────
# Tell Playwright where the browsers live (same path as the install above).
ENV PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

# Pre-create the runs directory so it exists if no volume is mounted.
RUN mkdir -p runs

EXPOSE 8000
