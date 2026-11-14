"""Small shared helpers so every service doesn't reimplement JSON
request/response plumbing on top of http.server. Standard-library only -
no Flask/requests, so the project runs with zero `pip install`.
"""
import json               # stdlib JSON encode/decode - stands in for a framework's body parser
import urllib.request      # stdlib HTTP client used to make outbound calls to other services
import urllib.error        # exception types urllib.request raises on non-2xx responses


def send_json(handler, status, payload, extra_headers=None):  # writes a JSON HTTP response onto an http.server request handler
    body = json.dumps(payload).encode('utf-8')  # serialize the Python object to a JSON string, then to raw bytes
    handler.send_response(status)  # write the status line, e.g. "HTTP/1.1 200 OK"
    handler.send_header('Content-Type', 'application/json')  # tell the client the body is JSON
    handler.send_header('Content-Length', str(len(body)))  # tell the client exactly how many bytes to expect
    for key, value in (extra_headers or {}).items():  # extra_headers defaults to None, so fall back to an empty dict to iterate safely
        handler.send_header(key, value)  # write each caller-supplied header, e.g. x-served-by
    handler.end_headers()  # blank line marking the end of headers, per the HTTP spec
    handler.wfile.write(body)  # write the actual JSON bytes to the response socket


def read_json_body(handler):  # reads and parses a JSON request body off an http.server request handler
    length = int(handler.headers.get('Content-Length', 0) or 0)  # how many bytes the client says it's sending; default to 0 if missing
    if length == 0:  # no body was sent (e.g. a GET, or a POST with no payload)
        return {}  # nothing to parse, so just hand back an empty dict
    raw = handler.rfile.read(length)  # block and read exactly `length` bytes from the request socket
    return json.loads(raw) if raw else {}  # parse the bytes as JSON, or {} if somehow still empty


def http_json(method, url, payload=None, timeout=2):  # makes an outbound HTTP call and returns (status, parsed_body)
    """Like `fetch(url, {method, body}).then(r => r.json())`, but never
    raises on a non-2xx status - it returns (status, body) either way, same
    as the Node version checking `res.ok` instead of catching an exception.
    Network-level failures (connection refused, timeout) still raise, same
    as a real fetch() would reject on those.
    """
    data = json.dumps(payload).encode('utf-8') if payload is not None else None  # only build a body if the caller actually passed a payload
    headers = {'Content-Type': 'application/json'} if data is not None else {}  # only set Content-Type when we're actually sending a body
    req = urllib.request.Request(url, data=data, method=method, headers=headers)  # build the request object (doesn't send anything yet)
    try:  # urlopen raises HTTPError for 4xx/5xx responses, which we want to treat as normal, not exceptional
        with urllib.request.urlopen(req, timeout=timeout) as res:  # actually send the request; times out after `timeout` seconds
            body = res.read()  # read the full response body as bytes
            return res.status, (json.loads(body) if body else None)  # return (status code, parsed JSON or None if body was empty)
    except urllib.error.HTTPError as err:  # urlopen raises this for any non-2xx status instead of returning normally
        body = err.read()  # the error response still has a body (e.g. {"error": "..."}) - read it
        try:  # the error body might not actually be JSON (e.g. a raw HTML error page)
            parsed = json.loads(body) if body else None  # attempt to parse it as JSON
        except json.JSONDecodeError:  # the body wasn't valid JSON
            parsed = None  # fall back to None rather than letting the exception propagate
        return err.code, parsed  # return (status code, parsed body or None) just like the success path above
