#!/usr/bin/env python3
"""Fetch a site's key URLs and emit SEO/security-relevant facts as JSON. Stdlib only."""
import json, re, sys, urllib.request, urllib.error
from html.parser import HTMLParser

SENSITIVE = ["/.git/HEAD", "/.env", "/backup.sql", "/config.json", "/.DS_Store", "/phpinfo.php", "/server-status"]
MISSING = "/__prelaunch_missing__"


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = None; self.description = None; self.canonical = None; self.lang = None
        self.og = {}; self.twitter = {}; self.jsonld = []; self.h1_count = 0; self.links = []
        self.images_without_alt = 0; self._in_title = False; self._in_ld = False; self._buf = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html" and a.get("lang"): self.lang = a["lang"]
        elif tag == "title": self._in_title = True; self._buf = ""
        elif tag == "meta":
            name, prop, content = a.get("name") or "", a.get("property") or "", a.get("content") or ""
            if name == "description": self.description = content
            if prop.startswith("og:"): self.og[prop] = content
            if name.startswith("twitter:"): self.twitter[name] = content
        elif tag == "link" and "canonical" in (a.get("rel") or "").split(): self.canonical = a.get("href")
        elif tag == "script" and a.get("type") == "application/ld+json": self._in_ld = True; self._buf = ""
        elif tag == "h1": self.h1_count += 1
        elif tag == "a" and a.get("href"): self.links.append(a["href"])
        elif tag == "img" and "alt" not in a: self.images_without_alt += 1

    def handle_data(self, data):
        if self._in_title or self._in_ld: self._buf += data

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title: self.title = self._buf.strip(); self._in_title = False
        if tag == "script" and self._in_ld:
            self._in_ld = False
            try: self.jsonld.append(json.loads(self._buf))
            except json.JSONDecodeError: self.jsonld.append({"_invalid": self._buf[:200]})


def fetch(url, timeout):
    redirects = []
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            redirects.append(newurl); return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "pre-launch-probe/1"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, dict((k.lower(), v) for k, v in r.headers.items()), r.read(), redirects
    except urllib.error.HTTPError as e:
        return e.code, dict((k.lower(), v) for k, v in e.headers.items()), e.read(), redirects
    except Exception as e:
        return None, {}, str(e).encode(), redirects


def probe(base_url, timeout=10.0):
    base = base_url.rstrip("/")
    out = {"base": base, "pages": {}, "sensitive_paths": {}}
    for path in ["/", "/robots.txt", "/sitemap.xml", "/llms.txt", MISSING]:
        status, headers, body, redirects = fetch(base + path, timeout)
        text = body.decode("utf-8", "replace")
        entry = {"status": status, "headers": headers, "redirects": redirects}
        if path == "/":
            p = Page(); p.feed(text)
            entry.update(title=p.title, description=p.description, canonical=p.canonical, lang=p.lang,
                         og=p.og, twitter=p.twitter, jsonld=p.jsonld, h1_count=p.h1_count,
                         links=p.links, images_without_alt=p.images_without_alt)
        elif path == "/sitemap.xml":
            entry["urls"] = re.findall(r"<loc>\s*(.*?)\s*</loc>", text)
        elif path == MISSING:
            entry["body_snippet"] = text[:500]
        else:
            entry["body"] = text[:5000] if status == 200 else ""
        out["pages"][path] = entry
    for path in SENSITIVE:
        out["sensitive_paths"][path] = fetch(base + path, timeout)[0]
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: probe_url.py <base_url>")
    print(json.dumps(probe(sys.argv[1]), indent=2))
