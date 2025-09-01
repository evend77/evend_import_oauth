from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import os, pandas as pd, requests, subprocess, uuid, sqlite3
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import urllib.parse
import logging

app = Flask(__name__)
app.secret_key = 'UN_SECRET_POUR_SESSION'  # ⚠️ change-le en prod

# --- Chemins relatifs pour Render ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
SELENIUM_SCRIPT = os.path.join(BASE_DIR, 'evend_publish.py')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ------------------------
# Route pour l'import sur e-Vend
# ------------------------
@app.route("/post_evend", methods=["POST"])
def post_evend():
    import sys
    import os
    import uuid
    import subprocess
    from flask import request, flash, redirect, url_for

    # Vérifie si un fichier CSV a été envoyé
    if 'csv_file' not in request.files:
        flash("❌ Aucun fichier sélectionné.")
        return redirect(url_for('index'))

    file = request.files['csv_file']
    if file.filename == '':
        flash("❌ Aucun fichier sélectionné.")
        return redirect(url_for('index'))

    # Crée le dossier uploads si nécessaire
    UPLOAD_FOLDER = "uploads"
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # Sauvegarde le CSV dans le dossier uploads
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    # Récupère les valeurs par défaut depuis le formulaire
    default_values = {
        "type_annonce": request.form.get("type_annonce"),
        "categorie": request.form.get("categorie"),
        "titre": request.form.get("titre"),
        "description": request.form.get("description"),
        "condition": request.form.get("condition"),
        "retour": request.form.get("retour"),
        "garantie": request.form.get("garantie"),
        "prix": request.form.get("prix"),
        "stock": request.form.get("stock"),
        "livraison_type": request.form.get("livraison_type"),
        "livraison_ramassage": request.form.get("livraison_ramassage"),
        "frais_port_article": request.form.get("frais_port_article"),
        "frais_port_sup": request.form.get("frais_port_sup"),
        "photo_defaut": request.form.get("photo_defaut")
    }

    # Appelle ton script Python qui fait l'import sur e-Vend
    try:
        subprocess.run([
            "python3",
            "/opt/render/project/src/evend_publish.py",
            filepath
        ], check=True)
        flash("✅ Import terminé avec succès !")
    except subprocess.CalledProcessError as e:
        flash(f"❌ Erreur import: {e}")

    return redirect(url_for('index'))


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
    connected = False
    today_imported = 0
    remaining_quota = 0
    if user_id:
        tokens = get_user_tokens(user_id)
        if tokens:
            connected = True
            today_imported = get_import_count_today(user_id)
            remaining_quota = max(0, MAX_PER_DAY - today_imported)
    return render_template('index.html',
                           connected=connected,
                           today_imported=today_imported,
                           remaining_quota=remaining_quota)

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

# --- Import e-Vend ---
@app.route('/post_evend', methods=['POST'])
def post_evend():
    user_id = session.get('user_id')
    if not user_id:
        flash("⚠️ Session expirée.")
        return redirect(url_for('index'))

    if 'csv_file' not in request.files:
        flash("⚠️ Aucun fichier CSV sélectionné.")
        return redirect(url_for('index'))

    file = request.files['csv_file']
    if file.filename == '':
        flash("⚠️ Aucun fichier sélectionné.")
        return redirect(url_for('index'))

    safe_filename = f"csv_ebay_import_{uuid.uuid4().hex}.csv"
    file_path = os.path.join(UPLOAD_FOLDER, safe_filename)
    file.save(file_path)

    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        os.remove(file_path)
        flash(f"❌ CSV invalide: {e}")
        return redirect(url_for('index'))

    nb_items = len(df.index)
    today_imported = get_import_count_today(user_id)
    remaining_quota = max(0, MAX_PER_DAY - today_imported)
    if nb_items > remaining_quota:
        os.remove(file_path)
        flash(f"⚠️ Quota restant: {remaining_quota}, ton fichier contient {nb_items}.")
        return redirect(url_for('index'))

    try:
        result = subprocess.run(['python3', SELENIUM_SCRIPT, file_path], check=True, capture_output=True, text=True)
        add_import(user_id, nb_items)
        flash("✅ Import e-Vend terminé !")
        if result.stdout:
            flash(f"ℹ️ Logs:\n{result.stdout}")
        if result.stderr:
            flash(f"⚠️ Erreurs:\n{result.stderr}")
    except subprocess.CalledProcessError as e:
        flash(f"❌ Erreur import: {e}\nStdout:\n{e.stdout}\nStderr:\n{e.stderr}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

    return redirect(url_for('index'))

# --- Réinitialiser dernier CSV ---
@app.route('/reset_csv', methods=['POST'])
def reset_csv():
    user_id = session.get('user_id')
    if not user_id:
        flash("⚠️ Session expirée.")
        return redirect(url_for('index'))

    last_csv = get_last_csv_path(user_id)
    if last_csv and os.path.exists(last_csv):
        os.remove(last_csv)
        set_last_csv_path(user_id, None)
        flash("🧹 Dernier CSV eBay supprimé.")
    else:
        flash("ℹ️ Aucun CSV précédent à supprimer.")

    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
