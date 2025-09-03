import os
import sys
import pandas as pd
import requests
import tempfile
import time
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- Vérification argument CSV ---
if len(sys.argv) < 2:
    logging.error("Usage: python evend_publish.py <csv_file>")
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
FRAIS_PORT_ARTICLE = float(os.environ.get("frais_port_article", "0"))
FRAIS_PORT_SUP = float(os.environ.get("frais_port_sup", "0"))
USER_ID = os.environ.get("user_id", "unknown_user")

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

# --- Setup Selenium Chrome Headless ---
chrome_options = Options()
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
prefs = {"profile.managed_default_content_settings.images": 2}
chrome_options.add_experimental_option("prefs", prefs)

driver = webdriver.Chrome(options=chrome_options)
wait = WebDriverWait(driver, 20)

EVEND_LOGIN_URL = "https://www.e-vend.ca/login"
EVEND_NEW_LISTING_URL = "https://www.e-vend.ca/l/draft/00000000-0000-0000-0000-000000000000/new/details"

# --- Fichier de log pour index ---
LOG_FILE = f"/app/uploads/{USER_ID}_import_log.txt"
PROGRESS_FILE = f"/app/uploads/progress_{USER_ID}.txt"

def write_log(msg):
    print(msg)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(msg + "\n")
    except:
        pass

def save_progress(batch_index, idx):
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            f.write(f"{batch_index},{idx}\n")
    except:
        pass

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                line = f.readline()
                if line:
                    parts = line.strip().split(",")
                    return int(parts[0]), int(parts[1])
        except:
            pass
    return 0, -1  # Si rien, commencer depuis le début

# --- Charger l'état avant de commencer ---
last_batch, last_idx = load_progress()

# --- Login e-Vend ---
try:
    driver.get(EVEND_LOGIN_URL)
    wait.until(EC.presence_of_element_located((By.ID, "email")))
    driver.find_element(By.ID, "email").send_keys(EVEND_EMAIL)
    driver.find_element(By.ID, "password").send_keys(EVEND_PASSWORD)
    driver.find_element(By.ID, "loginBtn").click()
    wait.until(EC.presence_of_element_located((By.ID, "dashboard")))
    write_log("✅ Connecté à e-Vend avec succès.")
except Exception as e:
    write_log(f"❌ Échec du login: {e}")
    driver.quit()
    sys.exit(1)

def check_radio(driver, name, value_to_check):
    try:
        radios = driver.find_elements(By.NAME, name)
        for r in radios:
            if r.get_attribute("value") == value_to_check and not r.is_selected():
                r.click()
                return True
    except:
        pass
    return False

def upload_images(driver, image_urls):
    try:
        photo_fields = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        for i, url in enumerate(image_urls):
            if i >= len(photo_fields):
                write_log(f"⚠️ Pas assez de champs photo pour l'image {url}")
                break
            field = photo_fields[i]
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
                        tmp_file.write(response.content)
                        tmp_path = tmp_file.name
                    field.send_keys(tmp_path)
                    write_log(f"📸 Image uploadée: {url}")
                else:
                    write_log(f"⚠️ Impossible de télécharger {url}, code {response.status_code}")
            except Exception as e:
                write_log(f"⚠️ Erreur téléchargement image {url}: {e}")
    except Exception as e:
        write_log(f"⚠️ Impossible d’uploader les images: {e}")

def wait_for_success_message():
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".success-message, .alert-success")))
        return True
    except TimeoutException:
        return False

# --- Diviser en lots de 20 ---
BATCH_SIZE = 20
batches = [df[i:i+BATCH_SIZE] for i in range(0, len(df), BATCH_SIZE)]

for batch_index, batch in enumerate(batches):
    if batch_index < last_batch:
        continue  # Passer les lots déjà publiés
    write_log(f"--- DÉBUT lot {batch_index+1}/{len(batches)} ---")
    for idx, row in batch.iterrows():
        if batch_index == last_batch and idx <= last_idx:
            continue  # Passer les articles déjà publiés

        try:
            write_log(f"📌 Publication article {idx+1} lot {batch_index+1}")
            annonce_type = str(row.get('type_annonce', 'Vente classique') or 'Vente classique')
            categorie = str(row.get('categorie', 'Autre') or 'Autre')
            titre = str(row.get('titre', 'Titre manquant') or 'Titre manquant')
            description = str(row.get('description', 'Description non disponible') or 'Description non disponible')
            condition = str(row.get('condition', 'Non spécifié') or 'Non spécifié')
            retour = str(row.get('retour', 'Non') or 'Non')
            garantie = str(row.get('garantie', 'Non') or 'Non')
            prix = float(row.get('prix', 0.0) or 0.0)
            stock = int(row.get('stock', 1) or 1)

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
                "frais_port_article": str(FRAIS_PORT_ARTICLE),
                "frais_port_sup": str(FRAIS_PORT_SUP)
            }
            for field_id, value in fields.items():
                try:
                    el = driver.find_element(By.ID, field_id)
                    if field_id in ["prix", "stock", "frais_port_article", "frais_port_sup"]:
                        el.clear()
                    el.send_keys(value)
                except NoSuchElementException:
                    write_log(f"⚠️ Champ '{field_id}' non trouvé.")

            check_radio(driver, "livraison_type", livraison_type)
            if livraison_ramassage_value:
                try:
                    ramassage_field = driver.find_element(By.ID, "livraison_ramassage")
                    ramassage_field.clear()
                    ramassage_field.send_keys(livraison_ramassage_value)
                except NoSuchElementException:
                    write_log("⚠️ Champ livraison ramassage non trouvé.")

            if image_urls:
                upload_images(driver, image_urls)

            try:
                driver.find_element(By.ID, "submitBtn").click()
                if wait_for_success_message():
                    write_log(f"✅ Article publié: {titre}")
                else:
                    write_log(f"⚠️ Pas de confirmation publication pour: {titre}")
            except Exception as e:
                write_log(f"❌ Impossible de soumettre l'article {titre}: {e}")

            # --- Keep-alive pour Render gratuit ---
            try:
                requests.get("https://evend-import-oauth.onrender.com/")
            except:
                pass

            # --- Sauvegarde progression ---
            save_progress(batch_index, idx)
            time.sleep(2)  # pause 2s entre articles

        except Exception as e:
            write_log(f"❌ Erreur article {idx+1} lot {batch_index+1}: {e}")
            continue

    write_log(f"--- FIN lot {batch_index+1}/{len(batches)} ---")
    time.sleep(3)  # pause 3s entre lots pour Render

driver.quit()
write_log("🎯 Toutes les publications terminées.")


