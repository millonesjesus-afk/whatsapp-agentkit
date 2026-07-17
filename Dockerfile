FROM python:3.11-slim
WORKDIR /app
# ffmpeg: convierte las notas de voz grabadas en el navegador (WebM/Opus,
# lo único que produce MediaRecorder de forma confiable) a OGG/Opus, el
# único formato de audio que acepta la API de WhatsApp para notas de voz.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD uvicorn agent.main:app --host 0.0.0.0 --port ${PORT:-8000}
