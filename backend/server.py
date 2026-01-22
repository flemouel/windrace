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
import signal


BACKEND_LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs', 'server.log'))
FRONTEND_LOG_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs', 'frontend.log'))
LOG_LEVEL = "DEBUG"


def write_log(level, message, log_file, status=200, size='-'):
    """Write a log entry to the specified log file in common log format."""
    # DEBUG = all logs, INFO = info+error, ERROR = error only.
    current = (LOG_LEVEL or "").upper()
    lvl = (level or "INFO").upper()
    if current == "ERROR" and lvl != "ERROR":
        return
    if current == "INFO" and lvl == "DEBUG":
        return
    if lvl not in ("DEBUG", "INFO", "ERROR"):
        lvl = "INFO"
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    timestamp = time.strftime('%d/%b/%Y %H:%M:%S', time.localtime())
    line = f'127.0.0.1 - - [{timestamp}] "{lvl} {message}" {status} {size}\n'
    with open(log_file, 'a') as f:
        f.write(line)


def log(level, message, status=200, size='-'):
    """Append a line to logs/server.log in common log format."""
    write_log(level, message, BACKEND_LOG_FILE, status, size)


def logf(level, message, status=200, size='-'):
    """Append a frontend log to logs/frontend.log in common log format."""
    write_log(level, message, FRONTEND_LOG_FILE, status, size)


class WindGameHandler(SimpleHTTPRequestHandler):
    LEADERBOARD_JSON = os.path.join(os.path.dirname(__file__), '..', 'resdata', 'record_data.json')
    LEADERBOARD_HTML = os.path.join(os.path.dirname(__file__), '..', 'resdata', 'record_table.html')
    STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))
    _route_cache = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=self.STATIC_DIR, **kwargs)

    def do_GET(self):
        # Parse the URL.
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Debug: log GET request details.
        log("DEBUG", f"GET request - Full path: {self.path}")
        log("DEBUG", f"GET request - Parsed path: '{path}'")
        log("DEBUG", f"GET request - Query params: {query}")

        # Route for wind-data.php (wind data).
        if path == '/scripts/wind-data.php':
            self.handle_wind_service(query)
        # Route for wind-status.php (wind status).
        elif path == '/scripts/wind-status.php':
            self.handle_wind_status()
        # Route for sailing route.php (MPC/beam tacks).
        elif path == '/scripts/route.php':
            self.handle_route(query)
        # Route for record_table.html (leaderboard).
        elif path == '/resdata/record_table.html':
            self.handle_leaderboard()
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
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length else ""
        body_params = urllib.parse.parse_qs(body, keep_blank_values=True)
        merged_params = {}
        merged_params.update(query_params)
        for key, value in body_params.items():
            merged_params[key] = value

        # Debug: log POST request details.
        log("DEBUG", f"POST request - Full path: {self.path}")
        log("DEBUG", f"POST request - Parsed path: '{path}'")
        log("DEBUG", f"POST request - Query params: {query_params}")
        log("DEBUG", f"POST request - Body params: {body_params}")

        # Route for record.php (record scores).
        if path == '/scripts/record.php':
            self.handle_record(merged_params)
        # Route for log.php (frontend logging).
        elif path == '/scripts/log.php':
            self.handle_frontend_log(merged_params)
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
                    log("INFO", f"Real data loaded: {len(cls._real_wind_data['direction'])} points")
            except FileNotFoundError:
                log("ERROR", f"Data file not found: {wind_data_path}")
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
                'speed': real_data['speed'],
                'length': len(real_data['direction'])
            }
        else:
            # Fallback if data is unavailable.
            log("ERROR", "Using fallback data")
            response = {
                'timestamp': timestamp,
                'direction': [45.0] * 6001,
                'speed': [5.0] * 6001,
                'length': 6001
            }

        self.send_json_response(response)

    def handle_record(self, query):
        """Record game results."""
        # Read finalresult from request params.
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

        achievement = ""

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
            leaderboard.sort(key=lambda e: e.get('total_sailed') if e.get('total_sailed') is not None else float("inf"))
            leaderboard = leaderboard[:10]
            self.save_leaderboard(leaderboard)
            self.save_leaderboard_html(leaderboard)
            record_id = entry['id']

        response = {
            'id': record_id,
            'recordtime': recordtime,
            'total_sailed': total_sailed
        }

        self.send_json_response(response)

    def handle_frontend_log(self, query):
        """Log frontend events to logs/frontend.log."""
        level = query.get('level', ['INFO'])[0].upper()
        message = query.get('message', [''])[0]

        # Validate log level
        if level not in ('DEBUG', 'INFO', 'ERROR'):
            level = 'INFO'

        # Log to frontend log file
        logf(level, message)

        # Send success response
        response = {
            'status': 'ok',
            'logged': True
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
                start_index=start_index,
                near_threshold=near_threshold,
                near_delay=near_delay,
                far_delay=far_delay,
            )
            result_steps = result.get('steps', 0)
            result_tacks = result.get('tacks', [])
            result_total = result.get('total_sailed', 0)
            result_distance = result.get('distance_to_mark', 0)
            result_traj = result.get('trajectory', [])
        else:
            try:
                import beam_realmove
            except ImportError:
                self.send_json_response({'tacks': '', 'steps': 0, 'total_sailed': 0})
                return
            wind_dir, wind_speed = beam_realmove.load_wind_data(wind_path)
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
                start_index=start_index,
                near_threshold=near_threshold,
                near_delay=near_delay,
                far_delay=far_delay,
            )
            if result is None:
                self.send_json_response({'tacks': '', 'steps': 0, 'total_sailed': 0})
                return
            result_steps = result.step_count
            result_tacks = result.tacks
            result_total = result.boat.total_distance
            result_distance = self.haversine_m(result.boat.lat, result.boat.lng, finish_lat, finish_lng)
            result_traj = result.trajectory

        # No need to offset tacks since start_index is now passed to mpc_plan_real
        # and indices are already absolute
        tacks_list = result_tacks
        tacks_preview = tacks_list[:10]
        log(
            "INFO",
            f"route {method} steps={result_steps} distance_to_mark={round(result_distance, 2)} "
            f"total_sailed={round(result_total, 2)} tacks={tacks_preview} total={len(tacks_list)}"
        )
        log("DEBUG", f"DEBUG MPC trajectory")
        for step, decision, lat, lng in result_traj:
            log("DEBUG", f"route {method} trajectory (planned) {step:04d} {decision} {lat:.7f} {lng:.7f}")
        payload = {
            'method': method,
            'tacks': ",".join(tacks_list),
            'steps': result_steps,
            'total_sailed': result_total,
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
        entries = sorted(
            entries,
            key=lambda e: e.get('total_sailed') if e.get('total_sailed') is not None else float("inf")
        )
        entries = entries[:25]
        lines = [
            "<div class='results'>",
            "<a id='results' name='results' class='placeholder'></a>",
            "<h2 class='screen-only'>Top 25</h2>",
            "<table class='leaderboard'>",
            "<thead><tr>"
            "<th>Sailed</th>"
            "<th>Boat</th>"
            "<th>Straight-line distance</th>"
            "<th>Distance to mark (&lt;20m)</th>"
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

            if None in (start_lat, start_lng, finish_lat, finish_lng) or not total_sailed:
                straight = "-"
                efficiency = "-"
            else:
                straight_dist = self.haversine_m(start_lat, start_lng, finish_lat, finish_lng)
                straight = f"{straight_dist:.1f} m"
                efficiency = f"{(straight_dist / total_sailed) * 100:.1f}%"

            sailed_cell = f"{total_sailed} m"
            lat_cell = "-" if None in (start_lat, start_lng) else f"{start_lat:.5f} / {start_lng:.5f}"
            long_cell = "-" if None in (finish_lat, finish_lng) else f"{finish_lat:.5f} / {finish_lng:.5f}"
            lines.append(
                "<tr>"
                f"<td>{sailed_cell}</td>"
                f"<td>{name}</td>"
                f"<td>{straight}</td>"
                f"<td>{score} m</td>"
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
    log("INFO", f"WindGame server started at http://localhost:{port}")
    log("INFO", "Press Ctrl+C to stop")
    print(f"🌊 WindGame server started at http://localhost:{port}")
    print("⛵ Press Ctrl+C to stop")

    def handle_sigterm(signum, frame):
        log("INFO", "Server interrupted (SIGTERM)")
        print("⛔ Server interrupted (SIGTERM)")
        httpd.shutdown()
    signal.signal(signal.SIGTERM, handle_sigterm)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("INFO", "Server interrupted (KeyboardInterrupt)")
        print("⛔ Server interrupted (KeyboardInterrupt)")
    finally:
        httpd.server_close()

if __name__ == '__main__':
    run()
