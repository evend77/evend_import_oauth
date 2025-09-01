import sys
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

if len(sys.argv) < 4:
    logging.error("Usage: python evend_publish.py <csv_file> <evend_email> <evend_password>")
    sys.exit(1)

csv_file = sys.argv[1]
EVEND_EMAIL = sys.argv[2]
EVEND_PASSWORD = sys.argv[3]

if not os.path.exists(csv_file):
    logging.error(f"Fichier CSV introuvable: {csv_file}")
    sys.exit(1)

df = pd.read_csv(csv_file)
if df.empty:
    logging.error("Le CSV est vide.")
    sys.exit(1)

# --- Selenium Chrome Headless pour Render ---
from selenium.webdriver.chrome.service import Service

chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")  # sécurise sur Render

# chemin par défaut sur Render
chrome_service = Service("/usr/bin/chromedriver")
driver = webdriver.Chrome(service=chrome_service, options=chrome_options)

wait = WebDriverWait(driver, 10)

# --- URL e-Vend ---
EVEND_LOGIN_URL = "https://www.e-vend.ca/login"
EVEND_NEW_LISTING_URL = "https://www.e-vend.ca/l/draft/00000000-0000-0000-0000-000000000000/new/details"

# --- Login automatique e-Vend ---
try:
    driver.get(EVEND_LOGIN_URL)
    wait.until(EC.presence_of_element_located((By.ID, "email")))
    driver.find_element(By.ID, "email").send_keys(EVEND_EMAIL)
    driver.find_element(By.ID, "password").send_keys(EVEND_PASSWORD)
    driver.find_element(By.ID, "loginBtn").click()
    wait.until(EC.presence_of_element_located((By.ID, "dashboard")))  # ajuster au sélecteur réel
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
        annonce_type = row.get('type_annonce', 'Vente classique')
        categorie = row.get('categorie', 'Autre')
        titre = row.get('titre', 'Titre manquant')
        description = row.get('description', 'Description non disponible')
        condition = row.get('condition', 'Non spécifié')
        retour = row.get('retour', 'Non')
        garantie = row.get('garantie', 'Non')
        prix = row.get('prix', 0.0)
        stock = row.get('stock', 1)
        livraison = row.get('livraison_type', 'Standard')
        livraison_ramassage = row.get('livraison_ramassage', '')
        frais_port_article = row.get('frais_port_article', 0)
        frais_port_sup = row.get('frais_port_sup', 0)
        image_url = row.get('photo_defaut', '')

        driver.get(EVEND_NEW_LISTING_URL)
        wait.until(EC.presence_of_element_located((By.ID, "type_annonce")))

        # --- Remplissage formulaire ---
        driver.find_element(By.ID, "type_annonce").send_keys(annonce_type)
        driver.find_element(By.ID, "categorie").send_keys(categorie)
        driver.find_element(By.ID, "titre").send_keys(titre)
        driver.find_element(By.ID, "description").send_keys(description)
        driver.find_element(By.ID, "condition").send_keys(condition)
        driver.find_element(By.ID, "retour").send_keys(retour)
        driver.find_element(By.ID, "garantie").send_keys(garantie)
        driver.find_element(By.ID, "prix").clear()
        driver.find_element(By.ID, "prix").send_keys(str(prix))
        driver.find_element(By.ID, "stock").clear()
        driver.find_element(By.ID, "stock").send_keys(str(stock))
        driver.find_element(By.ID, "livraison_type").send_keys(livraison)
        driver.find_element(By.ID, "livraison_ramassage").send_keys(livraison_ramassage)
        driver.find_element(By.ID, "frais_port_article").clear()
        driver.find_element(By.ID, "frais_port_article").send_keys(str(frais_port_article))
        driver.find_element(By.ID, "frais_port_sup").clear()
        driver.find_element(By.ID, "frais_port_sup").send_keys(str(frais_port_sup))

        if image_url:
            try:
                driver.find_element(By.ID, "photo_defaut").send_keys(image_url)
            except NoSuchElementException:
                logging.warning("Champ photo non trouvé, passage à l'article suivant.")

        driver.find_element(By.ID, "submitBtn").click()
        time.sleep(2)
        logging.info(f"✅ Article publié: {titre}")

    except Exception as e:
        logging.error(f"❌ Erreur publication article {index+1}: {e}")
        continue

driver.quit()
logging.info("🎯 Toutes les publications terminées.")
