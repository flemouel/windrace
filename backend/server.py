#!/usr/bin/env python3
"""
Simple HTTP server for WindGame with simulated PHP endpoints.
"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import html
import random
import time
import math
import urllib.parse
import os
import sys


class WindGameHandler(SimpleHTTPRequestHandler):
    LEADERBOARD_JSON = os.path.join(os.path.dirname(__file__), '..', 'resdata', 'record_data.json')
    LEADERBOARD_HTML = os.path.join(os.path.dirname(__file__), '..', 'resdata', 'record_table.html')
    _route_cache = {}

    def do_GET(self):
        # Parse the URL.
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Route for service.php (wind data).
        if path == '/scripts/wind-data.php':
            self.handle_wind_service(query)
        # Route for wind-status.php (wind status).
        elif path == '/scripts/wind-status.php':
            self.handle_wind_status()
        # Route for record.php (record scores via GET).
        elif path == '/scripts/record.php':
            self.handle_record()
        # Route for route.php (MPC/beam tacks).
        elif path == '/scripts/route.php':
            self.handle_route(query)
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
        # Route for record_table.html (leaderboard).
        elif path == '/resdata/record_table.html':
            self.handle_leaderboard()
        # Route for wind-status.php.
        elif path == '/scripts/wind-status.php':
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
        finishindex = int(query.get('finishindex', [0])[0])
        total_sailed = int(query.get('total_sailed', [0])[0])
        start_lat = float(query.get('start_lat', [0])[0])
        start_lng = float(query.get('start_lng', [0])[0])
        finish_lat = float(query.get('finish_lat', [0])[0])
        finish_lng = float(query.get('finish_lng', [0])[0])

        # Determine achievement badge based on performance
        achievement = ""
        if finalresult > 0:
            if finalresult >= 100:
                achievement = "Outstanding!"
            elif finalresult >= 50:
                achievement = "Great job!"
            elif finalresult >= 20:
                achievement = "Well done!"

        leaderboard = self.load_leaderboard()
        recordtime = int(time.time())
        duplicate = None
        for existing in leaderboard:
            if (
                existing.get('boat_name') == boat_name
                and existing.get('score') == finalresult
                and existing.get('timestamp') == starttime
                and existing.get('total_sailed') == total_sailed
                and existing.get('start_lat') == start_lat
                and existing.get('start_lng') == start_lng
                and existing.get('finish_lat') == finish_lat
                and existing.get('finish_lng') == finish_lng
                and existing.get('finishindex') == finishindex
            ):
                duplicate = existing
                break

        if duplicate:
            achievement = "Record already saved"
            record_id = duplicate.get('id')
            recordtime = duplicate.get('recordtime', recordtime)
            total_sailed = duplicate.get('total_sailed', total_sailed)
        else:
            entry = {
                'id': random.randint(100000, 999999),
                'boat_name': boat_name,
                'score': finalresult,
                'timestamp': starttime,
                'recordtime': recordtime,
                'tacks': tacks,
                'total_sailed': total_sailed,
                'start_lat': start_lat,
                'start_lng': start_lng,
                'finish_lat': finish_lat,
                'finish_lng': finish_lng,
                'finishindex': finishindex
            }
            leaderboard.append(entry)
            leaderboard.sort(key=lambda e: e.get('score', 0), reverse=True)
            leaderboard = leaderboard[:10]
            self.save_leaderboard(leaderboard)
            self.save_leaderboard_html(leaderboard)
            record_id = entry['id']

        response = {
            'id': record_id,
            'achievement': achievement,
            'recordtime': recordtime,
            'total_sailed': total_sailed
        }

        self.send_json_response(response)


    def handle_route(self, query):
        """Return tack sequence for MPC or beam search."""
        method = query.get('method', [''])[0].strip().lower()
        if method not in ('mpc', 'beam'):
            self.send_json_response({'tacks': '', 'steps': 0, 'total_sailed': 0})
            return

        def read_float(key, default):
            try:
                return float(query.get(key, [default])[0])
            except (TypeError, ValueError):
                return default

        def read_int(key, default):
            try:
                return int(query.get(key, [default])[0])
            except (TypeError, ValueError):
                return default

        start_lat = read_float('start_lat', 0.0)
        start_lng = read_float('start_lng', 0.0)
        finish_lat = read_float('finish_lat', 0.0)
        finish_lng = read_float('finish_lng', 0.0)
        start_index = read_int('start_index', 0)
        horizon = read_int('horizon', 60)
        tackangle = read_float('tackangle', 43.0)
        goal = read_float('goal', 20.0)
        alpha = read_float('alpha', 1.0)
        near_threshold = read_float('near_threshold', 200.0)
        near_delay = read_int('near_delay', 10)
        far_delay = read_int('far_delay', 20)
        beam_width = read_int('beam_width', 200)

        cache_key = (
            method,
            start_lat,
            start_lng,
            finish_lat,
            finish_lng,
            start_index,
            horizon,
            tackangle,
            goal,
            alpha,
            near_threshold,
            near_delay,
            far_delay,
            beam_width,
        )
        if cache_key in self._route_cache:
            self.send_json_response(self._route_cache[cache_key])
            return

        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        or_dir = os.path.join(base_dir, 'research', 'OR')
        if or_dir not in sys.path:
            sys.path.append(or_dir)

        wind_path = os.path.join(base_dir, 'winddata', 'wind_data.json')
        if method == 'mpc':
            try:
                import mpc_realmove
            except ImportError:
                self.send_json_response({'tacks': '', 'steps': 0, 'total_sailed': 0})
                return
            wind_dir, wind_speed = mpc_realmove.load_wind_data(wind_path)
            if start_index > 0:
                wind_dir = wind_dir[start_index:]
                wind_speed = wind_speed[start_index:]
            result = mpc_realmove.mpc_plan_real(
                wind_dir,
                wind_speed,
                start_lat,
                start_lng,
                finish_lat,
                finish_lng,
                tackangle=tackangle,
                horizon=horizon,
                goal_dist=goal,
                alpha=alpha,
                near_threshold=near_threshold,
                near_delay=near_delay,
                far_delay=far_delay,
            )
        else:
            try:
                import beam_realmove
            except ImportError:
                self.send_json_response({'tacks': '', 'steps': 0, 'total_sailed': 0})
                return
            wind_dir, wind_speed = beam_realmove.load_wind_data(wind_path)
            if start_index > 0:
                wind_dir = wind_dir[start_index:]
                wind_speed = wind_speed[start_index:]
            result = beam_realmove.beam_search(
                wind_dir,
                wind_speed,
                start_lat,
                start_lng,
                finish_lat,
                finish_lng,
                tackangle=tackangle,
                horizon=horizon,
                goal_dist=goal,
                alpha=alpha,
                beam_width=beam_width,
                near_threshold=near_threshold,
                near_delay=near_delay,
                far_delay=far_delay,
            )
            if result is None:
                result = {'tacks': [], 'steps': 0, 'total_sailed': 0}
            else:
                result = {
                    'tacks': result.tacks,
                    'steps': result.step_count,
                    'total_sailed': result.boat.total_distance,
                }

        def offset_tacks(tacks, offset):
            if offset == 0:
                return tacks
            adjusted = []
            for tack in tacks:
                if len(tack) < 2:
                    continue
                label = tack[0]
                try:
                    idx = int(tack[1:])
                except ValueError:
                    continue
                adjusted.append(f"{label}{idx + offset}")
            return adjusted

        tacks_list = result.get('tacks', [])
        tacks_list = offset_tacks(tacks_list, start_index)
        payload = {
            'method': method,
            'tacks': ",".join(tacks_list),
            'steps': result.get('steps', 0),
            'total_sailed': result.get('total_sailed', 0),
        }
        self._route_cache[cache_key] = payload
        self.send_json_response(payload)

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
            "<a id='results' name='results' class='placeholder'></a>",
            "<h2 class='screen-only'>Top 10</h2>",
            "<table class='leaderboard'>",
            "<thead><tr>"
            "<th>Distance to mark (&lt;20m)</th>"
            "<th>Boat</th>"
            "<th>Straight-line distance</th>"
            "<th>Sailed</th>"
            "<th>Efficiency</th>"
            "<th>Start (Lat/long)</th>"
            "<th>Mark (Lat/Long)</th>"
            "<th>Course start date</th>"
            "<th>Record time</th>"
            "<th>Replay</th>"
            "</tr></thead>",
            "<tbody>"
        ]
        for entry in entries:
            score = entry.get('score', 0)
            name = entry.get('boat_name', 'Unknown')
            ts = entry.get('timestamp', 0)
            when = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(ts))
            record_ts = entry.get('recordtime', 0)
            record_when = time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(record_ts)) if record_ts else "-"
            finishindex = entry.get('finishindex', 0)
            tacks = html.escape(str(entry.get('tacks', '')))
            start_lat = entry.get('start_lat', None)
            start_lng = entry.get('start_lng', None)
            finish_lat = entry.get('finish_lat', None)
            finish_lng = entry.get('finish_lng', None)
            total_sailed = entry.get('total_sailed', 0)

            if None in (start_lat, start_lng, finish_lat, finish_lng):
                straight = "-"
                efficiency = "-"
            else:
                straight_dist = self.haversine_m(start_lat, start_lng, finish_lat, finish_lng)
                straight = f"{straight_dist:.1f} m"
                efficiency = f"{int((straight_dist / total_sailed) * 100)}%"

            sailed_cell = f"{total_sailed} m"
            lat_cell = "-" if None in (start_lat, start_lng) else f"{start_lat:.5f} / {start_lng:.5f}"
            long_cell = "-" if None in (finish_lat, finish_lng) else f"{finish_lat:.5f} / {finish_lng:.5f}"
            lines.append(
                "<tr>"
                f"<td>{score} m</td>"
                f"<td>{name}</td>"
                f"<td>{straight}</td>"
                f"<td>{sailed_cell}</td>"
                f"<td>{efficiency}</td>"
                f"<td>{lat_cell}</td>"
                f"<td>{long_cell}</td>"
                f"<td>{when}</td>"
                f"<td>{record_when}</td>"
                f"<td><button class='leaderboard-replay' data-starttime='{ts}' data-finishindex='{finishindex}' data-tacks='{tacks}'>Replay</button></td>"
                "</tr>"
            )
        lines.append("</tbody></table>")
        lines.append("</div>")
        return "\n".join(lines)

    def save_leaderboard_html(self, entries):
        """Write the leaderboard HTML file."""
        os.makedirs(os.path.dirname(self.LEADERBOARD_HTML), exist_ok=True)
        html = self.render_leaderboard_html(entries)
        with open(self.LEADERBOARD_HTML, 'w') as f:
            f.write(html)

    def haversine_m(self, lat1, lon1, lat2, lon2):
        """Return great-circle distance in meters."""
        r = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
        return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def run(port=8000):
    server_address = ('', port)
    httpd = HTTPServer(server_address, WindGameHandler)
    print(f"🌊 WindGame server started at http://localhost:{port}")
    print(f"⛵ Press Ctrl+C to stop")
    print()
    httpd.serve_forever()

if __name__ == '__main__':
    run()
