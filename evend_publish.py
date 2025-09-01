import os
import sys
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import time
import logging

# --- Logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- Vérification argument CSV ---
if len(sys.argv) < 2:
    logging.error("Usage: python evend_publish.py <csv_file>")
    sys.exit(1)

csv_file = sys.argv[1]
if not os.path.exists(csv_file):
    logging.error(f"Fichier CSV introuvable: {csv_file}")
    sys.exit(1)

# --- Variables d'environnement depuis Flask ---
EVEND_EMAIL = os.environ.get("email")
EVEND_PASSWORD = os.environ.get("password")
LIVRAISON_RAMASSAGE_CHECK = os.environ.get("livraison_ramassage_check") == 'on'
LIVRAISON_EXPEDITION_CHECK = os.environ.get("livraison_expedition_check") == 'on'
LIVRAISON_RAMASSAGE = os.environ.get("livraison_ramassage", "")
FRAIS_PORT_ARTICLE = os.environ.get("frais_port_article", "0")
FRAIS_PORT_SUP = os.environ.get("frais_port_sup", "0")

if not EVEND_EMAIL or not EVEND_PASSWORD:
    logging.error("❌ Email ou mot de passe e-Vend manquant dans les variables d'environnement.")
    sys.exit(1)

# --- Lecture CSV ---
try:
    df = pd.read_csv(csv_file)
except Exception as e:
    logging.error(f"❌ Impossible de lire le CSV: {e}")
    sys.exit(1)

if df.empty:
    logging.error("Le CSV est vide.")
    sys.exit(1)

# --- Selenium Chrome Headless pour Render ---
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_service = Service("/usr/bin/chromedriver")
driver = webdriver.Chrome(service=chrome_service, options=chrome_options)
wait = WebDriverWait(driver, 15)

# --- URLs e-Vend ---
EVEND_LOGIN_URL = "https://www.e-vend.ca/login"
EVEND_NEW_LISTING_URL = "https://www.e-vend.ca/l/draft/00000000-0000-0000-0000-000000000000/new/details"

# --- Login e-Vend ---
try:
    driver.get(EVEND_LOGIN_URL)
    wait.until(EC.presence_of_element_located((By.ID, "email")))
    driver.find_element(By.ID, "email").send_keys(EVEND_EMAIL)
    driver.find_element(By.ID, "password").send_keys(EVEND_PASSWORD)
    driver.find_element(By.ID, "loginBtn").click()
    wait.until(EC.presence_of_element_located((By.ID, "dashboard")))
    logging.info("✅ Connecté à e-Vend avec succès.")
except Exception as e:
    logging.error(f"❌ Échec du login e-Vend: {e}")
    driver.quit()
    sys.exit(1)

# --- Publication des articles ---
for index, row in df.iterrows():
    try:
        logging.info(f"📌 Publication de l'article {index+1}/{len(df)}")

        # --- Valeurs par défaut ---
        annonce_type = str(row.get('type_annonce', 'Vente classique') or 'Vente classique')
        categorie = str(row.get('categorie', 'Autre') or 'Autre')
        titre = str(row.get('titre', 'Titre manquant') or 'Titre manquant')
        description = str(row.get('description', 'Description non disponible') or 'Description non disponible')
        condition = str(row.get('condition', 'Non spécifié') or 'Non spécifié')
        retour = str(row.get('retour', 'Non') or 'Non')
        garantie = str(row.get('garantie', 'Non') or 'Non')
        prix = float(row.get('prix', 0.0) or 0.0)
        stock = int(row.get('stock', 1) or 1)
        livraison = "Ramassage" if LIVRAISON_RAMASSAGE_CHECK else "Expédition"
        livraison_ramassage = LIVRAISON_RAMASSAGE if LIVRAISON_RAMASSAGE_CHECK else ""
        frais_port_article = float(FRAIS_PORT_ARTICLE or 0.0)
        frais_port_sup = float(FRAIS_PORT_SUP or 0.0)
        image_url = str(row.get('photo_defaut', '') or '')

        # --- Accès au formulaire e-Vend ---
        driver.get(EVEND_NEW_LISTING_URL)
        wait.until(EC.presence_of_element_located((By.ID, "type_annonce")))

        # --- Remplissage formulaire avec vérification des champs ---
        fields = {
            "type_annonce": annonce_type,
            "categorie": categorie,
            "titre": titre,
            "description": description,
            "condition": condition,
            "retour": retour,
            "garantie": garantie,
            "prix": str(prix),
            "stock": str(stock),
            "livraison_type": livraison,
            "livraison_ramassage": livraison_ramassage,
            "frais_port_article": str(frais_port_article),
            "frais_port_sup": str(frais_port_sup)
        }

        for field_id, value in fields.items():
            try:
                element = driver.find_element(By.ID, field_id)
                element.clear() if field_id in ["prix", "stock", "frais_port_article", "frais_port_sup"] else None
                element.send_keys(value)
            except NoSuchElementException:
                logging.warning(f"⚠️ Champ '{field_id}' non trouvé, passage à l'article suivant.")

        # --- Photo ---
        if image_url:
            try:
                driver.find_element(By.ID, "photo_defaut").send_keys(image_url)
            except NoSuchElementException:
                logging.warning("⚠️ Champ photo non trouvé, passage à l'article suivant.")

        # --- Soumission ---
        try:
            driver.find_element(By.ID, "submitBtn").click()
            time.sleep(2)  # petit délai pour assurer l'envoi
            logging.info(f"✅ Article publié: {titre}")
        except Exception as e:
            logging.error(f"❌ Impossible de soumettre l'article {titre}: {e}")

    except Exception as e:
        logging.error(f"❌ Erreur publication article {index+1}: {e}")
        continue

# --- Nettoyage final ---
driver.quit()
logging.info("🎯 Toutes les publications terminées.")
