# ============================================================
# Imagen del Dashboard mmWave MR60BHA1
#
#   docker build -t dashboard-mmwave .
#   docker run --rm -p 8000:8000 -v "${PWD}/datos:/app/datos" dashboard-mmwave
#
# Ver la sección "Docker" del README: en Windows el contenedor
# no ve los puertos COM, así que sirve para usar el simulador.
# ============================================================

# --- Etapa 1: compilar la interfaz (Node solo se usa aquí) ---
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# --- Etapa 2: backend, que también sirve la interfaz compilada ---
FROM python:3.13-slim

# TZ: los CSV guardan la hora local con datetime.now(). Sin esto el contenedor
# usaría UTC y las horas quedarían corridas. Se cambia con: docker run -e TZ=...
ENV TZ=America/Santiago \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# tzdata para TZ; el grupo dialout permite abrir puertos serie en Linux.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --groups dialout app

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY --from=frontend /build/dist frontend/dist

RUN mkdir datos && chown app:app datos
VOLUME /app/datos

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/config', timeout=2)"

# Un solo proceso: la adquisición en curso vive en memoria y se comparte entre pestañas.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
