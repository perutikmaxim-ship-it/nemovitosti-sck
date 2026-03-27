# ============================================================
# Dockerfile – Reality Bot
# ============================================================
# Použití:
#   docker build -t reality-bot .
#   docker run -d --name reality-bot --env-file .env reality-bot

FROM python:3.11-slim

# Systémové závislosti pro lxml
RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Pracovní adresář
WORKDIR /app

# Nejdříve nainstalujeme závislosti (využití Docker cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Zkopírujeme zdrojový kód
COPY . .

# Vytvoříme adresář pro data
RUN mkdir -p /app/data

# Volume pro perzistentní data (SQLite databáze)
VOLUME ["/app/data"]

# Timezone
ENV TZ=Europe/Prague

# Spuštění bota
CMD ["python", "main.py"]
