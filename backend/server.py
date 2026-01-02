#!/usr/bin/env python3
"""
Simple HTTP server for WindGame with simulated PHP endpoints.
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import random
import time
import math
import urllib.parse
import os

class WindGameHandler(SimpleHTTPRequestHandler):
    LEADERBOARD_JSON = os.path.join(os.path.dirname(__file__), '..', 'resdata', 'resdata.json')
    LEADERBOARD_HTML = os.path.join(os.path.dirname(__file__), '..', 'resdata', 'table.html')

    def do_GET(self):
        # Parse the URL.
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Route for service.php (wind data).
        if path == '/scripts/service.php':
            self.handle_wind_service(query)
        # Route for wind.php (wind status).
        elif path == '/scripts/wind.php':
            self.handle_wind_status()
        # Route for record.php (record scores via GET).
        elif path == '/scripts/record.php':
            self.handle_record()
        # Route for avatar.php (user avatar).
        elif path == '/images/avatar.php':
            self.handle_avatar()
        # Route for boat.svg.php (boat image).
        elif path == '/images/boat.svg.php':
            self.handle_boat_svg(query)
        else:
            # Serve static files normally.
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        # Debug: print POST request details.
        print(f"[DEBUG] POST request - Full path: {self.path}")
        print(f"[DEBUG] POST request - Parsed path: '{path}'")
        print(f"[DEBUG] POST request - Query params: {query_params}")

        # Route for authentication (redirect to main page).
        if (path == '/' or path == '') and 'signin' in query_params:
            self.handle_signin()
        # Route for record.php (record scores).
        elif path == '/scripts/record.php':
            self.handle_record()
        # Route for save.php (share/save).
        elif path == '/scripts/save.php':
            self.handle_save()
        # Route for table.html (leaderboard).
        elif path == '/resdata/table.html':
            self.handle_leaderboard()
        # Route for wind.php.
        elif path == '/scripts/wind.php':
            self.handle_wind_status()
        else:
            self.send_error(404)

    # Load real site wind data at startup.
    _real_wind_data = None

    @classmethod
    def load_real_wind_data(cls):
        """Load real site wind data."""
        if cls._real_wind_data is None:
            wind_data_path = os.path.join(os.path.dirname(__file__), '..', 'winddata', 'wind_data.json')
            try:
                with open(wind_data_path, 'r') as f:
                    cls._real_wind_data = json.load(f)
                    print(f"✓ Real data loaded: {len(cls._real_wind_data['direction'])} points")
            except FileNotFoundError:
                print(f"⚠ Data file not found: {wind_data_path}")
                cls._real_wind_data = None
        return cls._real_wind_data

    def handle_wind_service(self, query):
        """Return real wind data from sailracer.net."""
        timestamp = int(query.get('timestamp', [time.time()])[0])

        # Load real data.
        real_data = self.load_real_wind_data()

        if real_data:
            # Use real site data.
            response = {
                'timestamp': real_data['timestamp'],
                'direction': real_data['direction'],
                'speed': real_data['speed']
            }
        else:
            # Fallback if data is unavailable.
            print("⚠ Using fallback data")
            response = {
                'timestamp': timestamp,
                'direction': [45.0] * 6001,
                'speed': [5.0] * 6001
            }

        self.send_json_response(response)

    def handle_record(self):
        """Record game results."""
        # Parse the URL to get query parameters.
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        # Read POST data if present.
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length:
            self.rfile.read(content_length)

        # Read finalresult from GET params.
        finalresult = int(query.get('finalresult', [0])[0])
        boat_name = query.get('boat_name', ['Unknown boat'])[0]
        starttime = int(query.get('starttime', [int(time.time())])[0])
        tacks = query.get('tacks', [''])[0]
        start_lat = float(query.get('start_lat', [0])[0])
        start_lng = float(query.get('start_lng', [0])[0])
        finish_lat = float(query.get('finish_lat', [0])[0])
        finish_lng = float(query.get('finish_lng', [0])[0])

        # Determine achievement badge based on performance (like record.php).
        achievement = ""
        if finalresult >= 100:
            achievement = "Outstanding!"
        elif finalresult >= 50:
            achievement = "Great job!"
        elif finalresult >= 20:
            achievement = "Well done!"

        leaderboard = self.load_leaderboard()
        entry = {
            'id': random.randint(100000, 999999),
            'boat_name': boat_name,
            'score': finalresult,
            'timestamp': starttime,
            'tacks': tacks,
            'start_lat': start_lat,
            'start_lng': start_lng,
            'finish_lat': finish_lat,
            'finish_lng': finish_lng
        }
        leaderboard.append(entry)
        leaderboard.sort(key=lambda e: e.get('score', 0), reverse=True)
        leaderboard = leaderboard[:10]
        self.save_leaderboard(leaderboard)
        self.save_leaderboard_html(leaderboard)

        response = {
            'id': entry['id'],
            'achievement': achievement
        }

        self.send_json_response(response)

    def handle_save(self):
        """Save a run for sharing."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length:
            self.rfile.read(content_length)

        track_id = f"{int(time.time())}_{random.randint(1000, 9999)}"

        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(track_id.encode())

    def handle_leaderboard(self):
        """Return the leaderboard."""
        if os.path.exists(self.LEADERBOARD_HTML):
            with open(self.LEADERBOARD_HTML, 'r') as f:
                html = f.read()
        else:
            html = self.render_leaderboard_html([])

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode())

    def handle_wind_status(self):
        """Return wind status."""
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
        """Simulate auth and redirect to the main page."""
        # Read and ignore POST data.
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length:
            self.rfile.read(content_length)

        # Redirect to the main page (simulated auth success).
        self.send_response(303)  # See Other
        self.send_header('Location', '/')
        self.end_headers()

    def handle_avatar(self):
        """Generate a default SVG avatar."""
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
        """Generate a boat SVG with the requested color (site original format)."""
        color = query.get('color', ['ff0000'])[0]

        # Original SVG from sailracer.net.
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
        """Send a JSON response."""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def load_leaderboard(self):
        """Load leaderboard entries from JSON."""
        if not os.path.exists(self.LEADERBOARD_JSON):
            return []
        try:
            with open(self.LEADERBOARD_JSON, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def save_leaderboard(self, entries):
        """Save leaderboard entries to JSON."""
        os.makedirs(os.path.dirname(self.LEADERBOARD_JSON), exist_ok=True)
        with open(self.LEADERBOARD_JSON, 'w') as f:
            json.dump(entries, f)

    def render_leaderboard_html(self, entries):
        """Render leaderboard HTML from entries."""
        lines = [
            "<div class='results'>",
            "<h2 class='screen-only'>Top 10</h2>"
        ]
        for entry in entries:
            score = entry.get('score', 0)
            name = entry.get('boat_name', 'Unknown')
            ts = entry.get('timestamp', 0)
            when = time.strftime('%a %H:%M UTC', time.gmtime(ts))
            lines.append(f"<p><a href='/windgame/view.php?w={entry.get('id', 0)}'>{score}m. {name} {when}</a></p>")
        lines.append("<p class='screen-only'>results in last day</p>")
        lines.append("</div>")
        lines.append("<div class='results'>")
        lines.append("<h2 class='screen-only'>Countries</h2>")
        lines.append("</div>")
        return "\n".join(lines)

    def save_leaderboard_html(self, entries):
        """Write the leaderboard HTML file."""
        os.makedirs(os.path.dirname(self.LEADERBOARD_HTML), exist_ok=True)
        html = self.render_leaderboard_html(entries)
        with open(self.LEADERBOARD_HTML, 'w') as f:
            f.write(html)

def run(port=8000):
    server_address = ('', port)
    httpd = HTTPServer(server_address, WindGameHandler)
    print(f"🌊 WindGame server started at http://localhost:{port}")
    print(f"⛵ Press Ctrl+C to stop")
    print()
    httpd.serve_forever()

if __name__ == '__main__':
    run()
