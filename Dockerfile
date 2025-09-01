# Utiliser une image Python avec Chrome déjà installé
FROM python:3.13-slim

# Installer les dépendances système pour Chrome et Selenium
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    xvfb \
    libnss3 \
    libgconf-2-4 \
    default-jdk \
    && rm -rf /var/lib/apt/lists/*

# Installer Google Chrome
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Installer ChromeDriver via Selenium Manager
RUN pip install --upgrade pip selenium pandas requests

# Définir le répertoire de travail
WORKDIR /app

# Copier tout le projet dans le conteneur
COPY . /app

# Créer le dossier uploads
RUN mkdir -p /app/uploads

# Exposer le port Flask
EXPOSE 10000

# Lancer l’application Flask
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "1"]
