"""Cloud LLM backend for PX Economy Lab. Python standard library only.

An independent, password-protected API server. The OpenAI key remains in
Render environment variables and is never emitted to the browser.
"""
from __future__ import annotations

import hmac
import http.server
import json
import os
import secrets

from llm_bridge import LLMBridge, DisabledError, ProviderError


PORT = int(os.getenv('PORT', '10000'))
PASSWORD = os.getenv('PX_API_PASSWORD', '')
ORIGIN = os.getenv('PX_ALLOWED_ORIGIN', '').strip().rstrip('/')

# Require secrets/configuration before opening a public endpoint.
if __name__ == '__main__':
    if len(PASSWORD) < 20 or not PASSWORD.isascii() or any(ch.isspace() for ch in PASSWORD):
        raise SystemExit('Set PX_API_PASSWORD to a strong 20+ character ASCII secret without spaces in Render Environment.')
    if not ORIGIN.startswith('https://') or '/' in ORIGIN[8:]:
        raise SystemExit('Set PX_ALLOWED_ORIGIN to your exact https://SITENAME.netlify.app URL (no trailing slash).')

bridge = LLMBridge()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'PX-API'

    def end_headers(self):
        origin = self.headers.get('Origin', '')
        if origin and hmac.compare_digest(origin, ORIGIN):
            self.send_header('Access-Control-Allow-Origin', ORIGIN)
            self.send_header('Vary', 'Origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def reply(self, status: int, body: dict):
        content = json.dumps(body, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def trusted_origin(self):
        origin = self.headers.get('Origin', '')
        return (not origin) or hmac.compare_digest(origin, ORIGIN)

    def authorized(self):
        return bool(PASSWORD) and hmac.compare_digest(self.headers.get('X-PX-Access-Password',''), PASSWORD)

    def do_OPTIONS(self):
        if not self.path.startswith('/api/') or not self.trusted_origin():
            return self.reply(403, {'error':'This site is not allowed to connect.'})
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-PX-Access-Password')
        self.send_header('Access-Control-Max-Age', '600')
        self.end_headers()

    def do_GET(self):
        if self.path == '/health':
            return self.reply(200, {'status':'ok'})
        if self.path != '/api/capabilities':
            return self.reply(404, {'error':'Not found.'})
        if not self.trusted_origin():
            return self.reply(403, {'error':'This site is not allowed to connect.'})
        if not self.authorized():
            return self.reply(401, {'error':'Wrong AI access password.'})
        return self.reply(200, bridge.status())

    def do_POST(self):
        if not self.trusted_origin():
            return self.reply(403, {'error':'This site is not allowed to connect.'})
        if not self.authorized():
            return self.reply(401, {'error':'Wrong AI access password.'})
        endpoints = {
            '/api/llm/interpret', '/api/llm/explain', '/api/llm/propose',
            '/api/llm/advise', '/api/llm/test', '/api/llm/cancel'
        }
        if self.path not in endpoints:
            return self.reply(404, {'error':'Unknown action.'})
        if not bridge.status()['enabled']:
            return self.reply(503, {'error':'LLM is not enabled on the server. Check Render Environment.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 256000:
                return self.reply(413, {'error':'Language endpoints accept up to 256 KB per action.'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object.')
            if self.path == '/api/llm/cancel':
                return self.reply(200, bridge.cancel(body.get('request_id')))
            with bridge.operation(body.get('request_id')):
                if self.path == '/api/llm/interpret':
                    result = bridge.interpret(body.get('plan', body.get('parsed')))
                elif self.path == '/api/llm/propose':
                    result = bridge.propose(body)
                elif self.path == '/api/llm/advise':
                    result = bridge.advise(body)
                elif self.path == '/api/llm/test':
                    result = bridge.test_connection()
                else:
                    result = bridge.explain(body['recommendations'], body['bindings'])
            return self.reply(200, result)
        except (DisabledError, ProviderError, ValueError, KeyError, TypeError) as exc:
            return self.reply(422, {'error':bridge._safe_error(str(exc))})
        except (ConnectionResetError, BrokenPipeError):
            # Client closed the browser tab or timed out; do not reveal anything.
            return None


def main():
    # 0.0.0.0 is necessary on Render. The OpenAI key is never served.
    print(f'PX LLM API listening on port {PORT}', flush=True)
    with http.server.ThreadingHTTPServer(('0.0.0.0', PORT), Handler) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
