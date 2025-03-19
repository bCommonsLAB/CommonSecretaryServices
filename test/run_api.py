"""
Skript zum Starten der API für Tests.
"""
import sys
import os

# Füge das Projektverzeichnis zum Pythonpfad hinzu
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importiere die Flask-App
from src.api.routes import blueprint as api_blueprint
from flask import Flask

app = Flask(__name__)
app.register_blueprint(api_blueprint, url_prefix='/api')

if __name__ == '__main__':
    print("Starting API server for testing on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True) 