"""Exercise the C fetch/cache boundary with a local HTTP server, never a speaker."""
import http.server
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

class CacheHTTP(unittest.TestCase):
    def test_fetch_outage_invalid_and_expired_cache(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            status = 200
            body = b'[{"coordinator":{"uuid":"RINCON_HTTP","roomName":"HTTP Room"}}]'
            def do_GET(self):
                self.send_response(self.status)
                self.send_header('Content-Length', str(len(self.body)))
                self.end_headers()
                self.wfile.write(self.body)
            def log_message(self, *args): pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        binary = Path(__file__).resolve().parent / 'bin' / 'test_sonos_api'
        try:
            with tempfile.TemporaryDirectory() as directory:
                cache = Path(directory) / 'rooms.json'
                def run(expected):
                    result = subprocess.run([str(binary), 'http://127.0.0.1:%s/zones' % server.server_port, str(cache)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                    return result
                run(0)
                before = cache.read_bytes()
                Handler.status = 503
                self.assertIn('using cached coordinators', run(0).stderr)
                Handler.status = 200
                Handler.body = b'[]'
                run(0)
                self.assertEqual(cache.read_bytes(), before)
                data = json.loads(before)
                data['fetched_at'] -= 86401
                cache.write_text(json.dumps(data))
                run(1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

if __name__ == '__main__': unittest.main()
