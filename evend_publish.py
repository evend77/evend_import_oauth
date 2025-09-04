import os
import sys
import pandas as pd
import requests
import tempfile
import time
import logging
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

LOCK_FILE = "/tmp/evend_publish.lock"
QUEUE_FILE = "/tmp/evend_publish_queue.json"

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
LIVRAISON_RAMASSAGE = os.environ.get("livraison_ramassage", "")
FRAIS_PORT_ARTICLE = float(os.environ.get("frais_port_article", "0"))
FRAIS_PORT_SUP = float(os.environ.get("frais_port_sup", "0"))
USER_ID = os.environ.get("user_id", f"user_{os.getpid()}")

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

# --- Gestion file d'attente ---
def load_queue():
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_queue(queue):
    try:
        with open(QUEUE_FILE, "w") as f:
            json.dump(queue, f)
    except:
        pass

def enter_queue(user_id, total_articles):
    queue = load_queue()
    if user_id not in [u['id'] for u in queue]:
        queue.append({'id': user_id, 'articles': total_articles})
        save_queue(queue)
    return queue

def leave_queue(user_id):
    queue = load_queue()
    queue = [u for u in queue if u['id'] != user_id]
    save_queue(queue)

# --- Ajouter utilisateur à la queue ---
queue = enter_queue(USER_ID, len(df))
position = next(i for i, u in enumerate(queue) if u['id'] == USER_ID)
if position > 0:
    articles_before = sum(u['articles'] for u in queue[:position])
    est_time = articles_before * 3  # estimation simple : 3s par article
    logging.error(f"⚠️ Système surchargé. Vous êtes en position #{position+1} dans la file d'attente. "
                  f"Temps estimé avant votre tour : ~{est_time} sec.")
    sys.exit(1)

# --- Fonction cleanup ---
def cleanup_and_exit(driver=None):
    if driver:
        try:
            driver.quit()
        except:
            pass
    leave_queue(USER_ID)

# --- Setup Selenium ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    prefs = {"profile.managed_default_content_settings.images": 2}
    chrome_options.add_experimental_option("prefs", prefs)
    return webdriver.Chrome(options=chrome_options)

EVEND_LOGIN_URL = "https://www.e-vend.ca/login"
EVEND_NEW_LISTING_URL = "https://www.e-vend.ca/l/draft/00000000-0000-0000-0000-000000000000/new/details"

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
    return 0, -1

# --- Charger état ---
last_batch, last_idx = load_progress()

# --- Fonctions auxiliaires ---
def login(driver, wait):
    driver.get(EVEND_LOGIN_URL)
    wait.until(EC.presence_of_element_located((By.ID, "email")))
    driver.find_element(By.ID, "email").send_keys(EVEND_EMAIL)
    driver.find_element(By.ID, "password").send_keys(EVEND_PASSWORD)
    driver.find_element(By.ID, "loginBtn").click()
    wait.until(EC.presence_of_element_located((By.ID, "dashboard")))
    write_log("✅ Connecté à e-Vend avec succès.")

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
    tmp_files = []
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
                        tmp_files.append(tmp_path)
                    field.send_keys(tmp_path)
                    write_log(f"📸 Image uploadée: {url}")
            except Exception as e:
                write_log(f"⚠️ Erreur téléchargement image {url}: {e}")
    finally:
        for f in tmp_files:
            try:
                os.remove(f)
            except:
                pass

def wait_for_success_message(wait):
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".success-message, .alert-success")))
        return True
    except TimeoutException:
        return False

# --- Diviser en lots ---
BATCH_SIZE = 20
batches = [df[i:i+BATCH_SIZE] for i in range(0, len(df), BATCH_SIZE)]

# --- Boucle principale ---
for batch_index, batch in enumerate(batches):
    if batch_index < last_batch:
        continue

    driver = None
    try:
        driver = get_driver()
        wait = WebDriverWait(driver, 20)
        login(driver, wait)

        write_log(f"--- DÉBUT lot {batch_index+1}/{len(batches)} ---")

        for idx, row in batch.iterrows():
            if batch_index == last_batch and idx <= last_idx:
                continue
            try:
                titre = str(row.get('titre', 'Titre manquant') or 'Titre manquant')
                write_log(f"📌 Publication article {idx+1} lot {batch_index+1}: {titre}")

                driver.get(EVEND_NEW_LISTING_URL)
                wait.until(EC.presence_of_element_located((By.ID, "type_annonce")))

                fields = {
                    "type_annonce": str(row.get('type_annonce', 'Vente classique')),
                    "categorie": str(row.get('categorie', 'Autre')),
                    "titre": titre,
                    "description": str(row.get('description', 'Description non disponible')),
                    "condition": str(row.get('condition', 'Non spécifié')),
                    "retour": str(row.get('retour', 'Non')),
                    "garantie": str(row.get('garantie', 'Non')),
                    "prix": str(float(row.get('prix', 0.0))),
                    "stock": str(int(row.get('stock', 1))),
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

                check_radio(driver, "livraison_type", "Expédition")
                if LIVRAISON_RAMASSAGE_CHECK:
                    try:
                        ramassage_field = driver.find_element(By.ID, "livraison_ramassage")
                        ramassage_field.clear()
                        ramassage_field.send_keys(LIVRAISON_RAMASSAGE)
                    except NoSuchElementException:
                        write_log("⚠️ Champ livraison ramassage non trouvé.")

                image_urls = []
                if 'photo_defaut' in row and pd.notna(row['photo_defaut']):
                    image_urls = [img.strip() for img in str(row['photo_defaut']).replace(';', ',').split(',') if img.strip()]
                if image_urls:
                    upload_images(driver, image_urls)

                try:
                    driver.find_element(By.ID, "submitBtn").click()
                    if wait_for_success_message(wait):
                        write_log(f"✅ Article publié: {titre}")
                    else:
                        write_log(f"⚠️ Pas de confirmation publication pour: {titre}")
                except Exception as e:
                    write_log(f"❌ Impossible de soumettre l'article {titre}: {e}")

                save_progress(batch_index, idx)
                time.sleep(2)

            except Exception as e:
                write_log(f"❌ Erreur article {idx+1} lot {batch_index+1}: {e}")
                continue

        write_log(f"--- FIN lot {batch_index+1}/{len(batches)} ---")
        time.sleep(3)

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

leave_queue(USER_ID)
write_log("🎯 Toutes les publications terminées.")






