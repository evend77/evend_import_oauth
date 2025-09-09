FROM python:3.11-slim

# Dépendances système
RUN apt-get update && apt-get install -y \
    wget unzip curl chromium chromium-driver \
    fonts-liberation libnss3 libxss1 libgconf-2-4 libappindicator3-1 \
    libatk-bridge2.0-0 libgtk-3-0 ttf-dejavu fonts-freefont-ttf \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Variables d'environnement
ENV PATH="/usr/bin:$PATH"
ENV PORT=5000  # valeur par défaut

# Copie du projet
WORKDIR /app
COPY . .

# Install requirements
RUN pip install --no-cache-dir -r requirements.txt

# Lancement app Flask via Gunicorn
CMD ["gunicorn", "app:app", "--workers=2", "--threads=4", "--bind", "0.0.0.0:5000"]
