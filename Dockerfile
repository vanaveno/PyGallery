FROM python:3.11-slim

# Instalace systémových závislostí (FFmpeg, nástroje pro WebP a curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libwebp-dev \
    webp \
    curl \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Instalace nejnovějšího yt-dlp pro stahování videí
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /app

# 1. Nejdříve zkopírujeme a nainstalujeme requirements (využijeme Docker cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Zkopírujeme zbytek zdrojových kódů aplikace
COPY . .

# Vytvoření potřebných složek, pokud by náhodou chyběly
RUN mkdir -p movie/thumbnails pics templates

EXPOSE 8001

# Spuštění Python aplikace (předpokládám hlavní soubor main.py)
CMD ["python", "main.py"]