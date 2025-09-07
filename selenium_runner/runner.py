import os
import sys
import pandas as pd
import requests
import tempfile
import time
import logging
import json
import threading
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# ---------------------------- Configuration ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "../uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

USER_ID = os.environ.get("user_id", f"user_{os.getpid()}")
LOG_FILE = os.path.join(UPLOAD_FOLDER, f"{USER_ID}_import_log.txt")
SESSION_FILE = os.path.join(UPLOAD_FOLDER, f"session_{USER_ID}.json")
QUEUE_FILE = os.path.join(UPLOAD_FOLDER, "evend_publish_queue.json")
PROGRESS_FILE = os.path.join(UPLOAD_FOLDER, f"progress_{USER_ID}.txt")

EVEND_EMAIL = os.environ.get("email")
EVEND_PASSWORD = os.environ.get("password")
LIVRAISON_RAMASSAGE_CHECK = os.environ.get("livraison_ramassage_check") == 'on'
FRAIS_PORT_ARTICLE = float(os.environ.get("frais_port_article", "0"))
FRAIS_PORT_SUP = float(os.environ.get("frais_port_sup", "0"))

SESSION_MAX_AGE = 24 * 3600  # 24h
BATCH_SIZE = 20

EVEND_LOGIN_URL = "https://www.e-vend.ca/login"
EVEND_NEW_LISTING_URL = "https://www.e-vend.ca/l/draft/00000000-0000-0000-0000-000000000000/new/details"

# ---------------------------- Log thread-safe ----------------------------
class LogWrapper:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def write(self, text):
        if text.strip():
            with self.lock:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(text)
                    f.flush()

    def flush(self):
        pass

log = LogWrapper(LOG_FILE)

def write_log(msg):
    print(msg, flush=True)
    try:
        log.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}\n")
    except Exception as e:
        print(f"⚠️ Impossible d'écrire dans le log: {e}", flush=True)

# ---------------------------- Queue ----------------------------
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
    queue = [u for u in load_queue() if u['id'] != user_id]
    save_queue(queue)

# ---------------------------- Selenium ----------------------------
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
    return webdriver.Chrome(options=chrome_options)

def save_session(driver):
    try:
        cookies = driver.get_cookies()
        session_data = {"timestamp": time.time(), "cookies": cookies}
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(session_data, f)
    except Exception as e:
        write_log(f"⚠️ Impossible de sauvegarder la session: {e}")

def load_session(driver):
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                session_data = json.load(f)
            if time.time() - session_data.get("timestamp", 0) > SESSION_MAX_AGE:
                write_log("⚠️ Session expirée, suppression.")
                os.remove(SESSION_FILE)
                return False
            driver.get(EVEND_LOGIN_URL)
            for cookie in session_data.get("cookies", []):
                cookie.pop('sameSite', None)
                driver.add_cookie(cookie)
            return True
        except Exception as e:
            write_log(f"⚠️ Impossible de charger la session: {e}")
    return False

# ---------------------------- Login ----------------------------
def login(driver, wait):
    write_log("🔹 Naviguer vers e-Vend")
    driver.get("https://www.e-vend.ca/")
    try:
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Connexion')]"))
        ).click()
    except TimeoutException:
        write_log("⚠️ Bouton Connexion non trouvé, peut-être déjà connecté")
    wait.until(EC.presence_of_element_located((By.NAME, "email")))
    driver.find_element(By.NAME, "email").send_keys(EVEND_EMAIL)
    driver.find_element(By.NAME, "password").send_keys(EVEND_PASSWORD)
    driver.find_element(By.XPATH, "//button[contains(text(),'Se connecter')]").click()
    wait.until(EC.presence_of_element_located((By.ID, "dashboard")))
    write_log("✅ Login réussi")
    save_session(driver)

# ---------------------------- CSV processing ----------------------------
def process_csv(csv_path):
    if not os.path.exists(csv_path):
        write_log(f"❌ CSV introuvable: {csv_path}")
        return
    df = pd.read_csv(csv_path)
    if df.empty:
        write_log("❌ CSV vide.")
        return

    queue = enter_queue(USER_ID, len(df))
    position = next((i for i, u in enumerate(queue) if u['id'] == USER_ID), 0)
    if position > 0:
        est_time = sum(u['articles'] for u in queue[:position]) * 3
        write_log(f"⚠️ Vous êtes en position #{position+1} dans la file. Estimation: ~{est_time}s")
        return

    driver = get_driver()
    wait = WebDriverWait(driver, 20)
    try:
        login(driver, wait)
        for idx, row in df.iterrows():
            titre = str(row.get('titre', 'Titre manquant'))
            write_log(f"📌 Publication article {idx+1}: {titre}")
            driver.get(EVEND_NEW_LISTING_URL)
            wait.until(EC.presence_of_element_located((By.ID, "type_annonce")))
            # Remplir les champs essentiels
            driver.find_element(By.ID, "type_annonce").send_keys(row.get('type_annonce', 'Vente classique'))
            driver.find_element(By.ID, "titre").send_keys(titre)
            driver.find_element(By.ID, "description").send_keys(row.get('description', ''))
            driver.find_element(By.ID, "prix").send_keys(str(row.get('prix', 5)))
            driver.find_element(By.ID, "stock").send_keys(str(row.get('stock', 1)))
            # Photo
            photo_url = row.get('photo_defaut')
            if photo_url:
                tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                tmp_file.write(requests.get(photo_url).content)
                tmp_file.close()
                driver.find_element(By.CSS_SELECTOR, "input[type='file']").send_keys(tmp_file.name)
                os.remove(tmp_file.name)
            # Submit
            try:
                driver.find_element(By.ID, "submitBtn").click()
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".success-message, .alert-success")))
                write_log("✅ Article publié avec succès")
            except TimeoutException:
                write_log("⚠️ Article publié mais confirmation non détectée")
    except Exception as e:
        write_log(f"❌ Erreur Selenium: {e}")
    finally:
        driver.quit()
        leave_queue(USER_ID)
        write_log("🎉 Fin du traitement CSV")

# ---------------------------- Folder Watcher ----------------------------
def watch_folder():
    processed = set()
    write_log(f"👀 Surveillance du dossier: {UPLOAD_FOLDER}")
    while True:
        for file in os.listdir(UPLOAD_FOLDER):
            path = os.path.join(UPLOAD_FOLDER, file)
            if path.endswith(".csv") and path not in processed:
                write_log(f"🆕 Nouveau CSV détecté: {file}")
                process_csv(path)
                processed.add(path)
        time.sleep(5)

# ---------------------------- Main ----------------------------
if __name__ == "__main__":
    if not EVEND_EMAIL or not EVEND_PASSWORD:
        write_log("❌ Email ou mot de passe e-Vend manquant dans les variables d'environnement.")
        sys.exit(1)
    watch_folder()
