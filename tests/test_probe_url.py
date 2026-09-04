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

def test_probe_extracts_seo_fields():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
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
