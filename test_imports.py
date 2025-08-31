import os
import pandas as pd
import requests
import subprocess
import uuid
import sqlite3
from flask import Flask

# Vérifie les modules
print("✅ Tous les modules importés correctement")

# Vérifie les dossiers
UPLOAD_FOLDER = '/home/evend/evend_import_oauth/uploads'
SELENIUM_SCRIPT = '/home/evend/evend_import_oauth/evend_publish.py'

print("UPLOAD_FOLDER existe ?", os.path.exists(UPLOAD_FOLDER))
print("SELENIUM_SCRIPT existe ?", os.path.exists(SELENIUM_SCRIPT))
