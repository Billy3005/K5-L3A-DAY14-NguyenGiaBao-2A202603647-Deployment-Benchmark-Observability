# ============================================================
# Production Dockerfile — multi-stage, non-root, có HEALTHCHECK
#   builder : cài dependencies vào virtualenv /opt/venv
#   runtime : chỉ copy virtualenv + source, không mang theo pip cache / build tool
# ============================================================

# ---------- Stage 1: builder ----------
FROM python:3.11-slim AS builder

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# COPY requirements.txt trước: sửa code không làm mất cache của layer pip install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ---------- Stage 2: runtime ----------
FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 10001 appuser

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser utils/ ./utils/

USER appuser

EXPOSE 8000

# Image slim không có curl nên dùng Python. Container phải lên được khi chưa có Redis,
# và /health không phụ thuộc Redis.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=3)" || exit 1

# `exec` thay shell bằng uvicorn → uvicorn là PID 1 và nhận SIGTERM khi `docker stop`.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
