#!/usr/bin/env python3
"""
Serveur HTTP simple pour WindGame avec support des endpoints PHP simulés
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import random
import time
import math
import urllib.parse
import os

class WindGameHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        # Parse the URL
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Route pour service.php (données de vent)
        if path == '/scripts/service.php':
            self.handle_wind_service(query)
        # Route pour wind.php (état du vent)
        elif path == '/scripts/wind.php':
            self.handle_wind_status()
        # Route pour record.php (enregistrement des scores via GET)
        elif path == '/scripts/record.php':
            self.handle_record()
        # Route pour avatar.php (avatar utilisateur)
        elif path == '/images/avatar.php':
            self.handle_avatar()
        # Route pour boat.svg.php (image du bateau)
        elif path == '/images/boat.svg.php':
            self.handle_boat_svg(query)
        else:
            # Servir les fichiers statiques normalement
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        # Debug: afficher les détails de la requête POST
        print(f"[DEBUG] POST request - Full path: {self.path}")
        print(f"[DEBUG] POST request - Parsed path: '{path}'")
        print(f"[DEBUG] POST request - Query params: {query_params}")

        # Route pour authentification (redirect vers page principale)
        if (path == '/' or path == '') and 'signin' in query_params:
            self.handle_signin()
        # Route pour record.php (enregistrement des scores)
        elif path == '/scripts/record.php':
            self.handle_record()
        # Route pour save.php (sauvegarde pour partage)
        elif path == '/scripts/save.php':
            self.handle_save()
        # Route pour table.html (leaderboard)
        elif path == '/resdata/table.html':
            self.handle_leaderboard()
        # Route pour wind.php
        elif path == '/scripts/wind.php':
            self.handle_wind_status()
        else:
            self.send_error(404)

    # Charger les vraies données du site au démarrage
    _real_wind_data = None

    @classmethod
    def load_real_wind_data(cls):
        """Charge les vraies données de vent du site"""
        if cls._real_wind_data is None:
            wind_data_path = os.path.join(os.path.dirname(__file__), '..', 'winddata', 'wind_data.json')
            try:
                with open(wind_data_path, 'r') as f:
                    cls._real_wind_data = json.load(f)
                    print(f"✓ Données réelles chargées: {len(cls._real_wind_data['direction'])} points")
            except FileNotFoundError:
                print(f"⚠ Fichier de données introuvable: {wind_data_path}")
                cls._real_wind_data = None
        return cls._real_wind_data

    def handle_wind_service(self, query):
        """Retourne les vraies données de vent du site sailracer.net"""
        timestamp = int(query.get('timestamp', [time.time()])[0])

        # Charger les vraies données
        real_data = self.load_real_wind_data()

        if real_data:
            # Utiliser les vraies données du site
            response = {
                'timestamp': real_data['timestamp'],
                'direction': real_data['direction'],
                'speed': real_data['speed']
            }
        else:
            # Fallback si les données ne sont pas disponibles
            print("⚠ Utilisation de données de secours")
            response = {
                'timestamp': timestamp,
                'direction': [45.0] * 6001,
                'speed': [5.0] * 6001
            }

        self.send_json_response(response)

    def handle_record(self):
        """Enregistre les résultats du jeu"""
        # Parse the URL to get query parameters
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        # Lire les données POST si présentes
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length:
            self.rfile.read(content_length)

        # Récupérer le finalresult depuis les paramètres GET
        finalresult = int(query.get('finalresult', [0])[0])

        # Déterminer le badge/achievement basé sur la performance (comme record.php)
        achievement = ""
        if finalresult >= 100:
            achievement = "Outstanding!"
        elif finalresult >= 50:
            achievement = "Great job!"
        elif finalresult >= 20:
            achievement = "Well done!"

        response = {
            'id': random.randint(100000, 999999),
            'achievement': achievement
        }

        self.send_json_response(response)

    def handle_save(self):
        """Sauvegarde une partie pour partage"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length:
            self.rfile.read(content_length)

        track_id = f"{int(time.time())}_{random.randint(1000, 9999)}"

        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(track_id.encode())

    def handle_leaderboard(self):
        """Retourne le leaderboard"""
        html = """<div class='results'>
<h2 class='screen-only'>Top 10</h2>
<p><a href='/windgame/view.php?w=166070'>53m. Nik GER Today 10:14 UTC</a></p>
<p><a href='/windgame/view.php?w=166071'>45m. John USA Today 09:32 UTC</a></p>
<p><a href='/windgame/view.php?w=166072'>38m. Marie FRA Today 08:15 UTC</a></p>
<p class='screen-only'>results in last day</p>
</div>
<div class='results'>
<h2 class='screen-only'>Countries</h2>
<p>GER 3</p><div class='scale' style='width:100%'></div>
<p>USA 2</p><div class='scale' style='width:80%'></div>
<p>FRA 2</p><div class='scale' style='width:80%'></div>
</div>"""

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode())

    def handle_wind_status(self):
        """Retourne l'état du vent"""
        wind_speed = 5.4 + random.uniform(0, 3)
        winners = random.randint(0, 5)
        total = 842423 + random.randint(1, 100)

        html = f"""<div id='ocean-wave' class='wave{random.randint(1,5)}'></div>
<div id='ocean-water'>
<p><b>Wind instrument online (simulated)</b></p>
<p>Wind speed {wind_speed:.1f}kn<br/>
Winners in last hour: {winners}/{winners + random.randint(1, 3)}<br/>
Totally played {total} times</p>
</div>"""

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode())

    def handle_signin(self):
        """Simule une authentification - redirige vers la page principale"""
        # Lire et ignorer les données POST
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length:
            self.rfile.read(content_length)

        # Rediriger vers la page principale (authentification simulée réussie)
        self.send_response(303)  # See Other
        self.send_header('Location', '/')
        self.end_headers()

    def handle_avatar(self):
        """Génère un avatar SVG par défaut"""
        colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c']
        color = random.choice(colors)

        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
  <circle cx="32" cy="32" r="32" fill="{color}"/>
  <circle cx="32" cy="24" r="10" fill="white" opacity="0.8"/>
  <path d="M 16 48 Q 16 36 32 36 Q 48 36 48 48" fill="white" opacity="0.8"/>
</svg>'''

        self.send_response(200)
        self.send_header('Content-type', 'image/svg+xml')
        self.end_headers()
        self.wfile.write(svg.encode())

    def handle_boat_svg(self, query):
        """Génère un SVG de bateau avec la couleur demandée (format original du site)"""
        color = query.get('color', ['ff0000'])[0]

        # SVG original du site sailracer.net
        svg = f'''<svg
	xmlns="http://www.w3.org/2000/svg"
	xmlns:se="http://svg-edit.googlecode.com"
	xmlns:xlink="http://www.w3.org/1999/xlink"
	xmlns:dc="http://purl.org/dc/elements/1.1/"
	xmlns:cc="http://creativecommons.org/ns#"
	xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
	xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
	width="100"
	height="100">

	<path fill="#{color}" fill-opacity="0.9" stroke="#000000" stroke-opacity="0.4" stroke-width="1" d="M 45,80 L 50,45 L 55,80 z" />



</svg>'''

        self.send_response(200)
        self.send_header('Content-type', 'image/svg+xml')
        self.end_headers()
        self.wfile.write(svg.encode())

    def send_json_response(self, data):
        """Envoie une réponse JSON"""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

def run(port=8000):
    server_address = ('', port)
    httpd = HTTPServer(server_address, WindGameHandler)
    print(f"🌊 Serveur WindGame démarré sur http://localhost:{port}")
    print(f"⛵ Appuyez sur Ctrl+C pour arrêter")
    print()
    httpd.serve_forever()

if __name__ == '__main__':
    run()
