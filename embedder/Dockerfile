FROM python:3.12-slim

# CPU wheels by default. For an NVIDIA GPU build:
#   docker build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124 embedder
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models

WORKDIR /app
RUN pip install --no-cache-dir torch --index-url ${TORCH_INDEX}
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .

RUN useradd --create-home --uid 1000 app && mkdir -p /models && chown app /models
USER app

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
