# Imagem ARM-friendly (Graviton na AWS) e enxuta
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependências de sistema mínimas (tesseract p/ OCR dos módulos financeiros/jurídico)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq5 tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
