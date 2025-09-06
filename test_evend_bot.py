# test_evend_bot.py
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

import os

# --- Options Chrome pour Selenium ---
chrome_options = Options()
chrome_options.add_argument("--headless")  # mode invisible
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920,1080")

# --- Chemin vers Chromium (Docker + Render) ---
CHROMIUM_PATH = "/usr/bin/chromium"
driver = webdriver.Chrome(service=Service(CHROMIUM_PATH), options=chrome_options)

try:
    driver.get("https://www.e-vend.ca/login")
    print("🔹 Page e-Vend chargée")

    # --- Vérifier si l'input email est présent ---
    try:
        email_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email"))
        )
        print("✅ Input email détecté, le bot n'est pas bloqué pour l'instant.")
    except TimeoutException:
        print("❌ Input email non détecté, e-Vend pourrait bloquer le bot.")

    # --- Vérifier un élément spécifique pour anti-bot ---
    try:
        captcha = driver.find_element(By.CLASS_NAME, "g-recaptcha")
        print("⚠️ CAPTCHA détecté, e-Vend bloque le bot !")
    except NoSuchElementException:
        print("✅ Aucun CAPTCHA détecté pour le moment.")

finally:
    driver.quit()

