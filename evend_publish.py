import os
import sys
import pandas as pd
import logging
import tempfile
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- Vérification argument CSV ---
if len(sys.argv) < 2:
    logging.error("Usage: python evend_publish_batch.py <csv_file>")
    sys.exit(1)

csv_file = sys.argv[1]
if not os.path.exists(csv_file):
    logging.error(f"Fichier CSV introuvable: {csv_file}")
    sys.exit(1)

# --- Variables d'environnement ---
EVEND_EMAIL = os.environ.get("email")
EVEND_PASSWORD = os.environ.get("password")
LIVRAISON_RAMASSAGE_CHECK = os.environ.get("livraison_ramassage_check") == 'on'
LIVRAISON_EXPEDITION_CHECK = os.environ.get("livraison_expedition_check") == 'on'
LIVRAISON_RAMASSAGE = os.environ.get("livraison_ramassage", "")
FRAIS_PORT_ARTICLE = os.environ.get("frais_port_article", "0")
FRAIS_PORT_SUP = os.environ.get("frais_port_sup", "0")

if not EVEND_EMAIL or not EVEND_PASSWORD:
    logging.error("❌ Email ou mot de passe e-Vend manquant.")
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

# --- Selenium Chrome Headless ---
chrome_options = Options()
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
prefs = {"profile.managed_default_content_settings.images": 2}
chrome_options.add_experimental_option("prefs", prefs)

driver = webdriver.Chrome(options=chrome_options)
wait = WebDriverWait(driver, 20)

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
    logging.error(f"❌ Échec du login: {e}")
    driver.quit()
    sys.exit(1)

# --- Fonctions utilitaires ---
def check_radio(driver, name, value_to_check):
    try:
        radios = driver.find_elements(By.NAME, name)
        for r in radios:
            if r.get_attribute("value") == value_to_check and not r.is_selected():
                r.click()
                return True
    except Exception as e:
        logging.warning(f"⚠️ Impossible de cocher '{value_to_check}' pour {name}: {e}")
    return False

def upload_images(driver, image_urls):
    try:
        photo_fields = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        for i, url in enumerate(image_urls):
            if i >= len(photo_fields):
                logging.warning(f"⚠️ Pas assez de champs photo pour l'image {url}")
                break
            field = photo_fields[i]
            try:
                import requests
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
                        tmp_file.write(response.content)
                        tmp_path = tmp_file.name
                    field.send_keys(tmp_path)
                    logging.info(f"📸 Image uploadée: {url}")
                else:
                    logging.warning(f"⚠️ Impossible de télécharger {url}, code {response.status_code}")
            except Exception as e:
                logging.warning(f"⚠️ Erreur téléchargement image {url}: {e}")
    except Exception as e:
        logging.warning(f"⚠️ Impossible d’uploader les images: {e}")

def wait_for_success_message():
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".success-message, .alert-success")))
        return True
    except TimeoutException:
        return False

# --- Publication par lot ---
BATCH_SIZE = 20
total_lots = (len(df)-1)//BATCH_SIZE + 1

for batch_index, start in enumerate(range(0, len(df), BATCH_SIZE)):
    batch = df.iloc[start:start+BATCH_SIZE]
    logging.info(f"🗂️ Traitement lot {batch_index+1}/{total_lots} ({len(batch)} annonces)")

    for index, row in batch.iterrows():
        try:
            logging.info(f"📌 Publication article {index+1}/{len(df)}")
            annonce_type = str(row.get('type_annonce', 'Vente classique') or 'Vente classique')
            categorie = str(row.get('categorie', 'Autre') or 'Autre')
            titre = str(row.get('titre', 'Titre manquant') or 'Titre manquant')
            description = str(row.get('description', 'Description non disponible') or 'Description non disponible')
            condition = str(row.get('condition', 'Non spécifié') or 'Non spécifié')
            retour = str(row.get('retour', 'Non') or 'Non')
            garantie = str(row.get('garantie', 'Non') or 'Non')
            prix = float(row.get('prix', 0.0) or 0.0)
            stock = int(row.get('stock', 1) or 1)
            frais_port_article = float(FRAIS_PORT_ARTICLE or 0.0)
            frais_port_sup = float(FRAIS_PORT_SUP or 0.0)

            image_urls = []
            if 'photo_defaut' in row and pd.notna(row['photo_defaut']):
                image_urls = [img.strip() for img in str(row['photo_defaut']).replace(';', ',').split(',') if img.strip()]

            livraison_type = "Expédition"
            livraison_ramassage_value = ""
            if LIVRAISON_RAMASSAGE_CHECK:
                livraison_type = "Ramassage"
                livraison_ramassage_value = LIVRAISON_RAMASSAGE

            driver.get(EVEND_NEW_LISTING_URL)
            wait.until(EC.presence_of_element_located((By.ID, "type_annonce")))

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
                "frais_port_article": str(frais_port_article),
                "frais_port_sup": str(frais_port_sup)
            }
            for field_id, value in fields.items():
                try:
                    el = driver.find_element(By.ID, field_id)
                    if field_id in ["prix", "stock", "frais_port_article", "frais_port_sup"]:
                        el.clear()
                    el.send_keys(value)
                except NoSuchElementException:
                    logging.warning(f"⚠️ Champ '{field_id}' non trouvé.")

            check_radio(driver, "livraison_type", livraison_type)
            if livraison_ramassage_value:
                try:
                    ramassage_field = driver.find_element(By.ID, "livraison_ramassage")
                    ramassage_field.clear()
                    ramassage_field.send_keys(livraison_ramassage_value)
                except NoSuchElementException:
                    logging.warning("⚠️ Champ livraison ramassage non trouvé.")

            if image_urls:
                upload_images(driver, image_urls)

            try:
                driver.find_element(By.ID, "submitBtn").click()
                if wait_for_success_message():
                    logging.info(f"✅ Article publié: {titre}")
                else:
                    logging.warning(f"⚠️ Pas de confirmation publication pour l'article: {titre}")
            except Exception as e:
                logging.error(f"❌ Impossible de soumettre l'article {titre}: {e}")

        except Exception as e:
            logging.error(f"❌ Erreur article {index+1}: {e}")
            continue

    logging.info(f"✅ Lot {batch_index+1} terminé. Pause 3s avant le suivant...")
    time.sleep(3)  # petit délai pour alléger la charge serveur

driver.quit()
logging.info("🎯 Toutes les publications terminées.")

