"""CDN (Chapter 1: "Content delivery network").
Serves static assets (CSS/JS) from a server dedicated to that job, with
long-lived cache headers, so the web tier never has to handle requests for
files that never change per-request. In production this would be a real
CDN edge node; here it's simulated as its own local process on its own port.
"""
import functools   # bind the served directory into the handler without a mutable class attribute
import os          # read PORT from the environment, and build the absolute PUBLIC_DIR path
import sys         # manipulate sys.path so the sibling http_util module can be imported
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer  # stdlib static file server + threaded server

sys.path.insert(0, os.path.dirname(__file__))  # add this file's own directory to the import path
from http_util import send_json  # noqa: E402  # shared JSON response helper (used only for /health)

PORT = int(os.environ.get('PORT', 7000))  # which port to listen on; defaults to 7000
PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'public-cdn'))  # absolute path to the folder of files this CDN serves


class Handler(SimpleHTTPRequestHandler):  # subclass the stdlib static file handler instead of reimplementing file serving
    def log_message(self, fmt, *args):  # override to silence the default per-request access log to stderr
        pass  # do nothing - keeps orchestrator.py's colored log output clean

    def do_GET(self):  # intercept GET before falling through to the stdlib file-serving behavior
        if self.path == '/health':  # liveness check used by the load balancer / orchestrator
            return send_json(self, 200, {'ok': True})  # simply confirm the process is up

        if self.path.startswith('/static/'):  # allow requests like /static/app.css
            self.path = self.path[len('/static'):]  # strip the "/static" prefix so SimpleHTTPRequestHandler looks up "/app.css" under PUBLIC_DIR
        super().do_GET()  # delegate to the stdlib handler to actually read and stream the file

    def end_headers(self):  # called by SimpleHTTPRequestHandler right before the header block ends
        self.send_header('Cache-Control', 'public, max-age=31536000, immutable')  # tell browsers to cache this response for a year, no revalidation
        self.send_header('x-served-by', 'cdn')  # marker header so you can see in devtools that the CDN answered, not the web tier
        super().end_headers()  # let the base class actually terminate the header block


if __name__ == '__main__':  # only runs when executed directly (as a subprocess), not if ever imported
    # functools.partial binds `directory` into the handler's __init__ kwargs -
    # setting it as a class attribute wouldn't work, since
    # SimpleHTTPRequestHandler.__init__ always overwrites self.directory
    # (defaulting to os.getcwd()) on every request.
    handler = functools.partial(Handler, directory=PUBLIC_DIR)  # pre-bind the directory kwarg so every instantiation gets it automatically
    server = ThreadingHTTPServer(('0.0.0.0', PORT), handler)  # bind on all interfaces so other processes/machines can reach it
    print(f'[cdn] listening on :{PORT}', flush=True)  # startup confirmation picked up by orchestrator.py's log streamer
    server.serve_forever()  # block forever, dispatching each incoming connection to a new Handler/thread
