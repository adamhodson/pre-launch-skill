import sys, pathlib, threading, json
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from probe_url import probe

HTML = b"""<!doctype html><html lang="en"><head><title>Acme</title>
<meta name="description" content="Widgets"><link rel="canonical" href="https://acme.test/">
<meta property="og:title" content="Acme"><meta name="twitter:card" content="summary">
<script type="application/ld+json">{"@type":"Organization","name":"Acme"}</script>
</head><body><h1>Hi</h1><a href="/about">About</a><img src="a.png"><img src="b.png" alt="B"></body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        routes = {"/": (200, HTML, "text/html"),
                  "/robots.txt": (200, b"User-agent: *\nSitemap: /sitemap.xml", "text/plain"),
                  "/sitemap.xml": (200, b'<urlset><url><loc>https://acme.test/</loc></url></urlset>', "application/xml")}
        status, body, ctype = routes.get(self.path, (404, b"nope", "text/plain"))
        self.send_response(status); self.send_header("Content-Type", ctype); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

def serve(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def test_probe_extracts_seo_fields():
    srv, base = serve(H)
    out = probe(base)
    root = out["pages"]["/"]
    assert root["status"] == 200 and root["title"] == "Acme" and root["lang"] == "en"
    assert root["description"] == "Widgets" and root["canonical"] == "https://acme.test/"
    assert root["og"]["og:title"] == "Acme" and root["twitter"]["twitter:card"] == "summary"
    assert root["jsonld"][0]["@type"] == "Organization"
    assert root["h1_count"] == 1 and root["images_without_alt"] == 1 and "/about" in root["links"]
    assert out["pages"]["/sitemap.xml"]["urls"] == ["https://acme.test/"]
    assert out["pages"]["/llms.txt"]["status"] == 404
    assert out["pages"]["/__prelaunch_missing__"]["status"] == 404
    assert out["sensitive_paths"]["/.env"] == 404
    json.dumps(out)  # serializable
    srv.shutdown()


MULTI_REL_HTML = b"""<!doctype html><html><head><title>T</title>
<link rel="icon canonical" href="https://acme.test/multi"></head><body></body></html>"""

class HMultiRel(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
        self.wfile.write(MULTI_REL_HTML)
    def log_message(self, *a): pass


def test_canonical_matches_multi_token_rel():
    srv, base = serve(HMultiRel)
    out = probe(base)
    assert out["pages"]["/"]["canonical"] == "https://acme.test/multi"
    srv.shutdown()


ALT_HTML = b"""<!doctype html><html><head><title>T</title></head><body>
<img src="a.png"><img src="b.png" alt=""><img src="c.png" alt="x"></body></html>"""

class HAlt(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
        self.wfile.write(ALT_HTML)
    def log_message(self, *a): pass


def test_images_without_alt_excludes_empty_alt():
    srv, base = serve(HAlt)
    out = probe(base)
    assert out["pages"]["/"]["images_without_alt"] == 1
    srv.shutdown()


class H500(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(500); self.send_header("Content-Type", "text/plain"); self.end_headers()
        self.wfile.write(b"boom")
    def log_message(self, *a): pass


def test_root_seo_keys_present_on_non_200():
    srv, base = serve(H500)
    out = probe(base)
    root = out["pages"]["/"]
    assert root["status"] == 500
    for key in ("title", "description", "canonical", "lang", "og", "twitter",
                "jsonld", "h1_count", "links", "images_without_alt"):
        assert key in root
    assert root["og"] == {} and root["links"] == [] and root["h1_count"] == 0
    srv.shutdown()


VALUELESS_HTML = b"""<!doctype html><html><head><title>T</title>
<link rel><meta property><meta name></head><body></body></html>"""

class HValueless(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
        self.wfile.write(VALUELESS_HTML)
    def log_message(self, *a): pass


def test_valueless_attrs_do_not_crash_parser():
    srv, base = serve(HValueless)
    out = probe(base)
    root = out["pages"]["/"]
    assert root["canonical"] is None and root["og"] == {}
    srv.shutdown()
