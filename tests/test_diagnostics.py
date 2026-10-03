import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import decky_diagnostics as d

class DiagnosticsTests(unittest.TestCase):
    def test_sensitive_event_payloads_omitted(self):
        text = '[main] Loading frontend\nDropping message qr_login=data:image/svg+xml;base64,SECRET\nAuthorization: SECRET'
        output = d.sanitize(text)
        self.assertIn('Loading frontend', output)
        self.assertNotIn('SECRET', output)
    def test_context_output_omits_urls(self):
        response = io.BytesIO(b'[{"title":"SharedJSContext","url":"https://private.example/secret"}]')
        response.status = 200
        with patch.object(d.urllib.request, 'urlopen', return_value=response), contextlib.redirect_stdout(io.StringIO()) as out:
            d.endpoint('http://127.0.0.1:8080/json', True)
        self.assertIn('SharedJSContext present: True', out.getvalue())
        self.assertNotIn('private.example', out.getvalue())
    def test_http_route_error_distinguished_from_connection_failure(self):
        error = urllib.error.HTTPError('http://localhost', 404, 'Missing', {}, None)
        with patch.object(d.urllib.request, 'urlopen', side_effect=error), contextlib.redirect_stdout(io.StringIO()) as out:
            d.endpoint('http://localhost')
        self.assertIn('server responded', out.getvalue())

if __name__ == '__main__': unittest.main()
