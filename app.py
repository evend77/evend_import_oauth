from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
import os, pandas as pd, requests, subprocess, uuid, sqlite3
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import urllib.parse
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# --- Nettoyage uploads avant lancement (safe) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

for f in os.listdir(UPLOAD_FOLDER):
    file_path = os.path.join(UPLOAD_FOLDER, f)
    try:
        # Supprimer uniquement les CSV temporaires
        if os.path.isfile(file_path) and f.endswith(".csv"):
            os.remove(file_path)
            print(f"🧹 CSV supprimé: {f}")
        # Si tu as des dossiers temporaires à nettoyer, tu peux les gérer ici
        # elif os.path.isdir(file_path):
        #     import shutil
        #     shutil.rmtree(file_path)
        #     print(f"🧹 Dossier supprimé: {f}")
    except Exception as e:
        print(f"❌ Impossible de supprimer {f}: {e}")




# --- Création de l'app Flask ---
app = Flask(__name__)
app.secret_key = 'UN_SECRET_POUR_SESSION'  # ⚠️ change-le en prod

# --- Config Upload accessible en écriture ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")  # => /opt/render/project/src/uploads
# Si tu veux du temporaire : UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), "uploads")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# --- Ajouter log utilisateur ---
def add_user_log_file(user_id, message):
    log_file = os.path.join(UPLOAD_FOLDER, f"{user_id}_import_log.txt")
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.utcnow().isoformat()}] {message}\n")
    except Exception as e:
        print(f"❌ Impossible d'écrire dans le log {log_file}: {e}")


# --- Nouveau log centralisé pour erreurs et événements ---
def log_event(user_id, message, is_error=False):
    """
    Log les événements utilisateur et les erreurs système.
    - user_id peut être 'system' pour les erreurs globales.
    """
    log_file = os.path.join(UPLOAD_FOLDER, f"{user_id}_import_log.txt")
    prefix = "❌ " if is_error else "ℹ️ "
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.utcnow().isoformat()}] {prefix}{message}\n")
    except Exception as e:
        print(f"❌ Impossible de logger {message} : {e}")







# --- Nouvelle route pour lire les logs Selenium / import (robuste) ---
@app.route('/get_import_log')
def get_import_log():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({"log": ["⚠️ Session expirée ou utilisateur non identifié."]})

        # Vérifie si le dossier existe
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        log_file = os.path.join(UPLOAD_FOLDER, f"{user_id}_import_log.txt")

        # Crée le fichier s'il n'existe pas
        if not os.path.exists(log_file):
            open(log_file, 'a').close()
            return jsonify({"log": ["ℹ️ Log créé, en attente d’événements..."]})

        # Lecture du fichier log
        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()[-1000:]  # récupère les 1000 dernières lignes
                lines = [line.strip() for line in lines if line.strip()]
        except Exception as e:
            lines = [f"❌ Impossible de lire le fichier de log: {e}"]

        return jsonify({"log": lines})

    except Exception as e:
        # Si quelque chose d’inattendu se produit
        system_log_file = os.path.join(UPLOAD_FOLDER, "system_import_log.txt")
        try:
            with open(system_log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.utcnow().isoformat()}] ❌ Erreur critique get_import_log: {e}\n")
        except:
            pass
        return jsonify({"log": [f"❌ Une erreur inattendue est survenue: {e}"]})




# --- Vérification au lancement ---
try:
    test_user = "startup_check"
    test_message = "✅ UPLOAD_FOLDER accessible et log OK"
    add_user_log_file(test_user, test_message)
    print(f"[INIT] Dossier UPLOAD_FOLDER OK -> {UPLOAD_FOLDER}")
except Exception as e:
    print(f"[INIT] ❌ Erreur accès UPLOAD_FOLDER {UPLOAD_FOLDER}: {e}")




# --- Lancement Selenium corrigé ---
def launch_selenium_import(user_id, file_path, env_vars):
    log_file = os.path.join(UPLOAD_FOLDER, f"{user_id}_import_log.txt")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            subprocess.Popen(
                ['python3', SELENIUM_SCRIPT, file_path],
                env=env_vars,
                stdout=f,
                stderr=f,
                start_new_session=True
            )
        add_user_log_file(user_id, f"✅ Import lancé pour {file_path}")
    except Exception as e:
        add_user_log_file(user_id, f"❌ Impossible de lancer l'import Selenium: {e}")



# --- Chemins relatifs pour Render ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
SELENIUM_SCRIPT = os.path.join(BASE_DIR, 'evend_publish.py')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- eBay API PROD ---
EBAY_CLIENT_ID = 'AlexBoss-eVendImp-PRD-bd29c22a7-4a223ad6'
EBAY_CLIENT_SECRET = 'PRD-d29c22a7bc6d-e864-4ffc-8934-e19a'
EBAY_REDIRECT_URI = 'https://evend-import.onrender.com/ebay_callback'  # À changer pour Render
EBAY_OAUTH_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_TRADING_API_URL = "https://api.ebay.com/ws/api.dll"
EBAY_COMPAT_LEVEL = "1191"
EBAY_SITE_ID_PRIMARY = "2"  # Canada

# --- Limites ---
MAX_PER_FILE = 500
MAX_PER_DAY = 2000

# --- SQLite ---
DB_PATH = os.path.join(BASE_DIR, "evend.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        access_token TEXT,
        refresh_token TEXT,
        expires_at TEXT,
        last_csv_path TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS imports (
        user_id TEXT,
        date TEXT,
        count INTEGER,
        PRIMARY KEY(user_id, date)
    )""")
    conn.commit()
    conn.close()

init_db()

# --- DB Helpers ---
def save_tokens(user_id, access_token, refresh_token, expires_in):
    expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
    conn = get_db()
    conn.execute("""
        INSERT INTO users (id, access_token, refresh_token, expires_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            access_token=excluded.access_token,
            refresh_token=excluded.refresh_token,
            expires_at=excluded.expires_at
    """, (user_id, access_token, refresh_token, expires_at))
    conn.commit()
    conn.close()

def get_user_tokens(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def set_last_csv_path(user_id, path_or_none):
    conn = get_db()
    conn.execute("UPDATE users SET last_csv_path=? WHERE id=?", (path_or_none, user_id))
    conn.commit()
    conn.close()

def get_last_csv_path(user_id):
    conn = get_db()
    row = conn.execute("SELECT last_csv_path FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return row['last_csv_path'] if row else None

def add_import(user_id, count):
    today = datetime.utcnow().date().isoformat()
    conn = get_db()
    row = conn.execute("SELECT count FROM imports WHERE user_id=? AND date=?", (user_id, today)).fetchone()
    if row:
        total = row['count'] + count
        conn.execute("UPDATE imports SET count=? WHERE user_id=? AND date=?", (total, user_id, today))
    else:
        conn.execute("INSERT INTO imports (user_id, date, count) VALUES (?,?,?)", (user_id, today, count))
    conn.commit()
    conn.close()

def get_import_count_today(user_id):
    today = datetime.utcnow().date().isoformat()
    conn = get_db()
    row = conn.execute("SELECT count FROM imports WHERE user_id=? AND date=?", (user_id, today)).fetchone()
    conn.close()
    return row['count'] if row else 0

# --- OAuth Helpers ---
def refresh_token(user_id, refresh_token):
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "https://api.ebay.com/oauth/api_scope"
    }
    try:
        r = requests.post(EBAY_OAUTH_TOKEN_URL, headers=headers, data=data,
                          auth=(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET))
        r.raise_for_status()
    except Exception as e:
        print(f"❌ Erreur réseau lors du refresh eBay : {e}")
        return None

    new_data = r.json()
    if 'access_token' in new_data:
        save_tokens(user_id, new_data['access_token'], refresh_token, new_data.get('expires_in', 7200))
        return new_data['access_token']
    return None

def get_valid_token(user_id):
    tokens = get_user_tokens(user_id)
    if not tokens:
        return None
    try:
        expires_at = datetime.fromisoformat(tokens['expires_at'])
    except Exception:
        expires_at = datetime.utcnow() - timedelta(seconds=1)

    if datetime.utcnow() >= expires_at:
        new_token = refresh_token(user_id, tokens.get('refresh_token'))
        if not new_token:
            conn = get_db()
            conn.execute("UPDATE users SET access_token=NULL, refresh_token=NULL, expires_at=NULL WHERE id=?", (user_id,))
            conn.commit()
            conn.close()
            return None
        return new_token
    return tokens.get('access_token')

# --- eBay Trading API Helpers ---
def get_text(parent, tag):
    ns = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}
    el = parent.find(f"ebay:{tag}", ns)
    return el.text if el is not None else None

def fetch_active_items(oauth_token, max_items=MAX_PER_FILE):
    headers = {
        "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
        "X-EBAY-API-SITEID": EBAY_SITE_ID_PRIMARY,
        "X-EBAY-API-COMPATIBILITY-LEVEL": EBAY_COMPAT_LEVEL,
        "X-EBAY-API-IAF-TOKEN": oauth_token,
        "Content-Type": "text/xml"
    }

    items = []
    page_number = 1
    per_page = min(max_items, 100)
    total_fetched = 0

    while total_fetched < max_items:
        body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{oauth_token}</eBayAuthToken>
  </RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Sort>TimeLeft</Sort>
    <Pagination>
      <EntriesPerPage>{per_page}</EntriesPerPage>
      <PageNumber>{page_number}</PageNumber>
    </Pagination>
  </ActiveList>
</GetMyeBaySellingRequest>
"""
        try:
            resp = requests.post(
                EBAY_TRADING_API_URL,
                headers=headers,
                data=body.encode("utf-8"),
                timeout=60
            )
            resp.raise_for_status()
        except Exception as e:
            logging.error(f"Erreur API eBay: {e}")
            break

        root = ET.fromstring(resp.text)
        ns = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}
        items_node = root.find(".//ebay:ActiveList/ebay:ItemArray", ns)
        if items_node is None:
            break

        item_elements = items_node.findall(".//ebay:Item", ns)
        if not item_elements:
            break

        for it in item_elements:
            try:
                sku = get_text(it, 'SKU') or "NO_SKU"
                title = get_text(it, 'Title') or "Titre manquant"
                desc = get_text(it, 'Description') or "Description non disponible"
                primary_cat = it.find(".//ebay:PrimaryCategory/ebay:CategoryName", ns)
                cat_name = primary_cat.text if primary_cat is not None else "Autre"
                price_text = get_text(it, 'CurrentPrice')
                prix = float(price_text) if price_text else 0.0
                condition_name = get_text(it, 'ConditionDisplayName') or "Non spécifié"
                qty_total_text = get_text(it, 'Quantity')
                qty_sold_text = get_text(it, 'QuantitySold')
                qty_total = int(qty_total_text) if qty_total_text and qty_total_text.isdigit() else 0
                qty_sold = int(qty_sold_text) if qty_sold_text and qty_sold_text.isdigit() else 0
                stock = max(qty_total - qty_sold, 0)
                images = it.findall(".//ebay:PictureURL", ns)
                image_url = images[0].text if images else "https://via.placeholder.com/150"

                items.append({
                    "sku": sku,
                    "titre": title,
                    "description": desc,
                    "prix": prix,
                    "condition": condition_name,
                    "categorie": cat_name,
                    "image_url": image_url,
                    "stock": stock
                })
                total_fetched += 1
                if total_fetched >= max_items:
                    break
            except Exception as e:
                logging.warning(f"Erreur sur un item: {e}")
                continue

        page_number += 1
        total_pages_el = root.find(".//ebay:PaginationResult/ebay:TotalNumberOfPages", ns)
        total_pages = int(total_pages_el.text) if total_pages_el is not None else 1
        if page_number > total_pages:
            break

    print(f"✅ Nombre total d'items actifs trouvés : {len(items)}")
    return items

# --- Routes ---
@app.route('/')
def index():
    user_id = session.get('user_id')

    # --- Logs dynamiques ---
    # On ne lit plus directement le log ici, JS fera le fetch
    user_logs = ""  
    system_logs = ""

    connected = False
    today_imported = 0
    remaining_quota = 0

    if user_id:
        tokens = get_user_tokens(user_id)
        if tokens:
            connected = True
            today_imported = get_import_count_today(user_id)
            remaining_quota = max(0, MAX_PER_DAY - today_imported)

    return render_template(
        'index.html',
        user_id=user_id,                 # nécessaire pour JS fetch
        connected=connected,
        today_imported=today_imported,
        remaining_quota=remaining_quota,
        user_logs=user_logs,
        system_logs=system_logs
    )


# --- OAuth eBay ---
@app.route('/login_ebay')
def login_ebay():
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    params = {
        "client_id": EBAY_CLIENT_ID,
        "redirect_uri": EBAY_REDIRECT_URI,
        "response_type": "code",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }
    return redirect("https://auth.ebay.com/oauth2/authorize?" + urllib.parse.urlencode(params))

@app.route('/ebay_callback')
def ebay_callback():
    code = request.args.get('code')
    if not code:
        flash("❌ OAuth eBay échoué.")
        return redirect(url_for('index'))
    user_id = session['user_id']
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": EBAY_REDIRECT_URI}
    r = requests.post(EBAY_OAUTH_TOKEN_URL, headers=headers, data=data, auth=(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET))
    token_data = r.json()
    if 'access_token' in token_data:
        save_tokens(user_id, token_data['access_token'], token_data.get('refresh_token'), token_data.get('expires_in', 7200))
        flash("✅ Connecté à eBay avec succès !")
    else:
        flash(f"❌ Erreur OAuth eBay: {token_data}")
    return redirect(url_for('index'))

@app.route('/logout_ebay')
def logout_ebay():
    user_id = session.get('user_id')
    if user_id:
        conn = get_db()
        conn.execute("UPDATE users SET access_token=NULL, refresh_token=NULL, expires_at=NULL WHERE id=?", (user_id,))
        conn.commit()
        conn.close()
    session.pop('user_id', None)
    flash("✅ Vous vous êtes déconnecté de eBay.")
    return redirect(url_for('index'))

# --- Télécharger CSV eBay ---
@app.route('/download_ebay_csv')
def download_ebay_csv():
    user_id = session.get('user_id')
    if not user_id or not get_user_tokens(user_id):
        flash("⚠️ Connecte d’abord ton compte eBay.")
        return redirect(url_for('index'))

    access_token = get_valid_token(user_id)
    if not access_token:
        flash("❌ Impossible d’obtenir un token eBay valide.")
        return redirect(url_for('index'))

    today_imported = get_import_count_today(user_id)
    remaining_quota = max(0, MAX_PER_DAY - today_imported)
    if remaining_quota <= 0:
        flash("⚠️ Quota journalier atteint (2000).")
        return redirect(url_for('index'))

    target_count = min(MAX_PER_FILE, remaining_quota)
    items = fetch_active_items(access_token, target_count)
    if not items:
        flash("📭 Aucune annonce active trouvée sur eBay.")
        return redirect(url_for('index'))

    df = pd.DataFrame(items)
    csv_path = os.path.join(UPLOAD_FOLDER, f"{user_id}_ebay_{uuid.uuid4().hex}.csv")
    df.to_csv(csv_path, index=False)
    set_last_csv_path(user_id, csv_path)

    flash(f"✅ CSV eBay prêt avec {len(df)} annonces.")
    return send_file(csv_path, as_attachment=True, download_name="csv_ebay_pret.csv", mimetype="text/csv")

# --- LogWrapper thread-safe pour import individuel ---
import threading

class LogWrapper:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def write(self, text):
        if text.strip():
            with self.lock:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(text)

    def flush(self):
        pass


# --- Route post_evend avec log unique par import ---
@app.route('/post_evend', methods=['GET', 'POST'])
def post_evend():
    if request.method == 'GET':
        return redirect(url_for('index'))

    user_id = session.get('user_id')
    if not user_id:
        flash("⚠️ Session expirée.")
        return redirect(url_for('index'))

    access_token = get_valid_token(user_id)
    if not access_token:
        flash("⚠️ Connecte d’abord ton compte eBay.")
        return redirect(url_for('login_ebay'))

    # --- CSV upload ou dernier CSV ---
    file = request.files.get('csv_file')
    if file and file.filename != '':
        safe_filename = f"csv_ebay_import_{uuid.uuid4().hex}.csv"
        file_path = os.path.join(UPLOAD_FOLDER, safe_filename)
        file.save(file_path)
        set_last_csv_path(user_id, file_path)
        add_user_log_file(user_id, "-------------------- NOUVEL IMPORT --------------------")
        add_user_log_file(user_id, f"📂 Fichier {file.filename} reçu et sauvegardé sous {safe_filename}")
    else:
        file_path = get_last_csv_path(user_id)
        if not file_path or not os.path.exists(file_path):
            flash("⚠️ Aucun fichier CSV disponible pour l'import.")
            return redirect(url_for('index'))
        add_user_log_file(user_id, "-------------------- REUTILISATION DU CSV EXISTANT --------------------")
        add_user_log_file(user_id, f"📂 Utilisation du dernier CSV existant : {file_path}")

    # --- Lecture CSV ---
    try:
        df = pd.read_csv(file_path)
        nb_items = len(df.index)
        add_user_log_file(user_id, f"📑 Lecture du CSV terminée : {nb_items} lignes trouvées")
    except Exception as e:
        flash(f"❌ CSV invalide: {e}")
        add_user_log_file(user_id, f"❌ CSV invalide : {e}")
        return redirect(url_for('index'))

    # --- Quota journalier ---
    today_imported = get_import_count_today(user_id)
    remaining_quota = max(0, MAX_PER_DAY - today_imported)
    if nb_items > remaining_quota:
        flash(f"⚠️ Quota restant: {remaining_quota}, ton fichier contient {nb_items}.")
        add_user_log_file(user_id, f"⚠️ Import annulé : quota restant {remaining_quota}, fichier {nb_items}")
        return redirect(url_for('index'))

    # --- Variables pour Selenium ---
    env_vars = os.environ.copy()
    env_vars.update({
        "email": request.form.get("evend_email", ""),
        "password": request.form.get("evend_password", ""),
        "type_annonce": request.form.get("type_annonce", ""),
        "categorie": request.form.get("categorie", ""),
        "titre": request.form.get("titre", ""),
        "description": request.form.get("description", ""),
        "condition": request.form.get("condition", ""),
        "retour": request.form.get("retour", ""),
        "garantie": request.form.get("garantie", ""),
        "prix": request.form.get("prix", ""),
        "stock": request.form.get("stock", ""),
        "frais_port_article": request.form.get("frais_port_article", ""),
        "frais_port_sup": request.form.get("frais_port_sup", ""),
        "photo_defaut": request.form.get("photo_defaut", ""),
        "livraison_ramassage_check": "on" if request.form.get("livraison_ramassage_check") else "",
        "livraison_expedition_check": "on" if request.form.get("livraison_expedition_check") else "",
        "livraison_ramassage": request.form.get("livraison_ramassage", "")
    })

    # --- Log unique par import ---
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    import_log_file = os.path.join(UPLOAD_FOLDER, f"{user_id}_import_{timestamp}.log")
    add_user_log_file(user_id, f"🚀 Import lancé, log individuel créé : {import_log_file}")

    # --- Lancer Selenium en arrière-plan ---
    try:
        wrapper = LogWrapper(import_log_file)

        def run_selenium():
            subprocess.Popen(
                ['python3', '-u', SELENIUM_SCRIPT, file_path],  # -u = mode unbuffered
                env=env_vars,
                stdout=wrapper,
                stderr=wrapper,
                bufsize=1,                  # line-buffered
                universal_newlines=True,    # texte au lieu de bytes
                start_new_session=True
            )

        threading.Thread(target=run_selenium, daemon=True).start()
        add_import(user_id, nb_items)
        flash(f"✅ Import lancé en arrière-plan ({nb_items} articles). Log séparé créé.")
        add_user_log_file(user_id, f"✅ Import démarré avec {nb_items} articles, fichier log : {import_log_file}")

    except Exception as e:
        flash(f"❌ Impossible de lancer l'import : {e}")
        add_user_log_file(user_id, f"❌ Erreur lancement Selenium : {e}")

    return redirect(url_for('index'))









import json

@app.route("/account_deletion", methods=["POST"])
def account_deletion():
    """
    Endpoint pour recevoir les notifications de suppression de compte eBay.
    - Accepte les requêtes POST JSON.
    - Logue le contenu reçu dans Render et stocke dans un fichier historique.
    - Retourne toujours un status 200 pour eBay.
    """
    try:
        # Lecture du JSON envoyé par eBay
        data = request.get_json(force=True, silent=True) or {}
        print("🔔 Notification eBay reçue :", data)

        # Stocker la notification dans un fichier historique
        history_file = os.path.join(UPLOAD_FOLDER, "account_deletion_history.json")
        if os.path.exists(history_file):
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        else:
            history = []

        history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        })

        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        return jsonify({"status": "received"}), 200

    except Exception as e:
        print("❌ Erreur account_deletion :", e)
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/test_bot')
def test_bot():
    """
    Lance un test du bot evend_bot_test.py en arrière-plan.
    - Écrit stdout et stderr dans /uploads/bot_test_log.txt
    """
    import subprocess
    import os

    log_file = os.path.join(UPLOAD_FOLDER, "bot_test_log.txt")
    try:
        with open(log_file, 'w', encoding='utf-8') as f:
            subprocess.Popen(
                ["python3", os.path.join(BASE_DIR, "evend_bot_test.py")],
                stdout=f,
                stderr=f,
                start_new_session=True  # Détache le processus du serveur Flask
            )
        return "✅ Test lancé. Vérifie le log dans /uploads/bot_test_log.txt"
    except Exception as e:
        print("❌ Erreur lancement test_bot :", e)
        return f"❌ Impossible de lancer le test : {e}"



@app.route("/view_account_deletion_history")
def view_account_deletion_history():
    history_file = os.path.join(UPLOAD_FOLDER, "account_deletion_history.json")
    if os.path.exists(history_file):
        with open(history_file, "r", encoding="utf-8") as f:
            content = f.read()
        return f"<pre>{content}</pre>"
    else:
        return "⚠️ Aucun historique trouvé."


@app.errorhandler(Exception)
def handle_exception(e):
    """
    Capture toutes les erreurs non gérées et les logue dans le fichier 'system'.
    """
    log_event('system', f"Erreur critique: {e}", is_error=True)
    return "❌ Une erreur est survenue. Vérifie les logs.", 500






# --- RUN SERVER ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Render fournit le PORT
    # debug=False pour sécuriser la production
    app.run(host="0.0.0.0", port=port, debug=False)

