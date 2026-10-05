#!/usr/bin/env python3
"""Build notazizelse.xyz.

    python build.py            production build -> dist/public   (links use https://<slug>.notazizelse.xyz)
    python build.py --dev      local build                        (links use http://<slug>.localhost:8795)
    python build.py --bundle   production build + dist/bundle.tgz for deploy/deploy.ps1

Output (what ~/site/public looks like on the server):
    apex/                 notazizelse.xyz
    p/<slug>/             <slug>.notazizelse.xyz: write-up page, img/, files/, docs/<name>/, and the app if any
"""
import argparse
import fnmatch
import hashlib
import html
import json
import re
import shutil
import sys
import tarfile
from pathlib import Path
from urllib.parse import unquote

import markdown
from PIL import Image

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
STATIC = ROOT / "static"
CACHE = ROOT / ".cache" / "img"
DIST = ROOT / "dist"
PUBLIC = DIST / "public"
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
         "&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;0,8..60,650;1,8..60,400&display=swap")
SKIP = [".DS_Store", "Thumbs.db", ".git", ".gitignore", "desktop.ini", ".nojekyll"]
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
esc = html.escape


class Site:
    def __init__(self, dev):
        self.scheme = "http" if dev else "https"
        self.domain = "localhost:8795" if dev else "notazizelse.xyz"
        self.data = json.loads((CONTENT / "site.json").read_text(encoding="utf-8"))
        self.projects = json.loads((CONTENT / "projects.json").read_text(encoding="utf-8"))["projects"]
        seen = set()
        for p in self.projects:
            if not SLUG_RE.match(p["slug"]) or p["slug"] in seen or p["slug"] == "www":
                sys.exit(f"bad or duplicate slug: {p['slug']}")
            seen.add(p["slug"])
        self.by_slug = {p["slug"]: p for p in self.projects}

    def home(self, path=""):
        return f"{self.scheme}://{self.domain}/{path}"

    def sub(self, slug, path=""):
        if slug not in self.by_slug:
            sys.exit(f"link to unknown project: {slug}")
        return f"{self.scheme}://{slug}.{self.domain}/{path}"

    def host(self, slug):
        return f"{slug}.{self.data['domain']}"


# ------------------------------------------------------------ text helpers

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def inline(site, text):
    """Escape text and turn [label](target) into links. A target of slug:<project> links to its subdomain."""
    out, last = [], 0
    for m in LINK_RE.finditer(text):
        out.append(esc(text[last:m.start()]))
        label, target = m.group(1), m.group(2)
        url = site.sub(target[5:]) if target.startswith("slug:") else target
        out.append(f'<a href="{esc(url)}">{esc(label)}</a>')
        last = m.end()
    out.append(esc(text[last:]))
    return "".join(out)


def paras(site, items):
    return "".join(f"<p>{inline(site, t)}</p>" for t in items)


# ------------------------------------------------------------ images

def image(src, out_dir, name=None, widths=(1600, 760)):
    """Resize src into out_dir as webp (cached in .cache/img). Returns full/small filenames and the full size."""
    src = Path(src) if Path(src).is_absolute() else ROOT / src
    if not src.exists():
        sys.exit(f"missing image: {src}")
    out_dir.mkdir(parents=True, exist_ok=True)
    name = name or re.sub(r"[^a-z0-9]+", "-", src.stem.lower()).strip("-")
    if src.suffix.lower() == ".svg":
        shutil.copy2(src, out_dir / f"{name}.svg")
        return {"full": f"{name}.svg", "small": f"{name}.svg", "w": 800, "h": 600}
    st = src.stat()
    key = hashlib.sha1(f"{src}|{st.st_size}|{st.st_mtime_ns}|{widths}".encode()).hexdigest()[:10]
    res = {}
    with Image.open(src) as im:
        im.load()
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("LA", "P") else "RGB")
        for label, w in zip(("full", "small"), widths):
            tw = min(w, im.width)
            th = round(im.height * tw / im.width)
            fname = f"{name}-{tw}.webp"
            cached = CACHE / f"{key}-{fname}"
            if not cached.exists():
                CACHE.mkdir(parents=True, exist_ok=True)
                im.resize((tw, th), Image.LANCZOS).save(cached, "WEBP", quality=84, method=6)
            shutil.copy2(cached, out_dir / fname)
            res[label] = fname
            if label == "full":
                res["w"], res["h"] = tw, th
    return res


def figure(src, alt, caption, out_dir, cls="", sizes="(min-width: 760px) 700px, 100vw"):
    v = image(src, out_dir)
    img = (f'<a href="/img/{v["full"]}"><img src="/img/{v["small"]}" srcset="/img/{v["small"]} 760w, /img/{v["full"]} {v["w"]}w" '
           f'sizes="{sizes}" width="{v["w"]}" height="{v["h"]}" alt="{esc(alt)}" loading="lazy"></a>')
    cap = f"<figcaption>{esc(caption)}</figcaption>" if caption else ""
    c = f' class="{cls}"' if cls else ""
    return f"<figure{c}>{img}{cap}</figure>"


# ------------------------------------------------------------ markdown docs

MD_EXT = ["tables", "fenced_code", "sane_lists", "toc"]
TAG_RE = re.compile(r'<(a|img)\b([^>]*?)\b(href|src)="([^"]*)"([^>]*)>', re.I)


def render_md(text, *, md_dir, out_root, repo=None, private=False, root=None, doc_map=None):
    """Markdown -> HTML. Local images are copied to <out_root>/docs/img; links to other rendered docs are rewritten;
    other relative links go to the file on GitHub, or are unlinked when the repo is private or unknown."""
    text = re.sub(r"\A\s*#\s+[^\n]+\n", "", text, count=1)   # the page already has the title
    body = markdown.markdown(text, extensions=MD_EXT, output_format="html")
    doc_map = doc_map or {}
    img_dir = out_root / "docs" / "img"

    def fix(m):
        tag, before, url, after = m.group(1).lower(), m.group(2), html.unescape(m.group(4)), m.group(5)
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", url, re.I):
            return m.group(0)
        path_part, _, frag = url.partition("#")
        frag = f"#{frag}" if frag else ""
        local = (Path(md_dir) / unquote(path_part)).resolve()
        if tag == "img":
            if local.is_file() and local.suffix.lower() in IMG_EXT:
                tag_name = hashlib.sha1(str(local).encode()).hexdigest()[:8] + "-" + re.sub(r"[^a-z0-9]+", "-", local.stem.lower())
                v = image(local, img_dir, name=tag_name)
                return f'<img{before}src="/docs/img/{v["full"]}"{after} loading="lazy">'
            return ""   # the source repo is missing this image
        if str(local) in doc_map:
            return f'<a{before}href="/docs/{doc_map[str(local)]}/{frag}"{after}>'
        if repo and not private and root:
            try:
                rel = local.relative_to(Path(root).resolve()).as_posix()
                return f'<a{before}href="https://github.com/{repo}/blob/HEAD/{rel}{frag}"{after}>'
            except ValueError:
                pass
        return "<a>"   # nowhere public to point at; keep the text

    body = TAG_RE.sub(fix, body)
    return body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")


# ------------------------------------------------------------ page shell

def shell(site, *, title, description, body, canonical, og_image=None, home_nav=False):
    d = site.data
    if home_nav:
        nav = '<a href="#projects">projects</a><a href="#about">about</a><a href="#work">work</a><a href="#contact">contact</a>'
    else:
        h = site.home()
        nav = f'<a href="{h}#projects">projects</a><a href="{h}#about">about</a><a href="{h}#contact">contact</a>'
    og = f'\n<meta property="og:image" content="{esc(og_image)}">' if og_image else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="author" content="{esc(d['name'])}">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}">{og}
<meta name="theme-color" content="#f6f4ee" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#161714" media="(prefers-color-scheme: dark)">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="/static/styles.css">
</head>
<body>
<div class="page">
<header class="site-head">
  <a class="who" href="{site.home()}">{esc(d['name'])}<span>{esc(d['handle'])}</span></a>
  <nav>{nav}</nav>
</header>
<main>
{body}
</main>
<footer>
  {esc(d['name'])}, Tashkent. Last updated {esc(d['updated'])}.<br>
  Every project has its own subdomain. The site is a static build served by a small Python server
  through a Cloudflare tunnel (<a href="https://github.com/notazizelse/notazizelse.xyz">source</a>).
</footer>
</div>
</body>
</html>
"""


def favicon():
    # Two plated holes on a green board.
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#1b6a41"/>'
            '<circle cx="11" cy="16" r="5" fill="#d9a441"/><circle cx="11" cy="16" r="2.2" fill="#1b6a41"/>'
            '<circle cx="21" cy="16" r="5" fill="#d9a441"/><circle cx="21" cy="16" r="2.2" fill="#1b6a41"/></svg>')


def write_static(dest):
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(STATIC / "styles.css", dest / "styles.css")
    (dest / "favicon.svg").write_text(favicon(), encoding="utf-8")


# ------------------------------------------------------------ home

def render_home(site, out):
    d = site.data
    img_dir = out / "img"
    photo = image(d["photo"]["src"], img_dir, name=d["photo"]["name"], widths=(700, 460))
    me = (f'<figure class="me"><img src="/img/{photo["small"]}" srcset="/img/{photo["small"]} 460w, /img/{photo["full"]} 700w" '
          f'sizes="230px" width="{photo["w"]}" height="{photo["h"]}" alt="{esc(d["photo"]["alt"])}">'
          f'<figcaption>{esc(d["photo"]["caption"])}</figcaption></figure>')

    strip = ""
    for s in d["strip"]:
        v = image(s["src"], img_dir, name=s["name"], widths=(900, 480))
        strip += (f'<a href="{site.sub(s["slug"])}"><figure><img src="/img/{v["small"]}" width="{v["w"]}" height="{v["h"]}" '
                  f'alt="{esc(s["alt"])}" loading="lazy"><figcaption>{esc(s["caption"])}</figcaption></figure></a>')

    def row(p):
        return (f'<li><span class="when">{esc(p["year"])}</span><span class="what"><a class="title" href="{site.sub(p["slug"])}">'
                f'{esc(p["title"])}</a><span class="host">{esc(site.host(p["slug"]))}</span>'
                f'<span class="sub">{inline(site, p["short"])}</span></span></li>')

    main_rows = "".join(row(p) for p in site.projects if not p.get("small"))
    small_rows = "".join(row(p) for p in site.projects if p.get("small"))
    now = "".join(f"<li>{inline(site, t)}</li>" for t in d["now"])
    work = "".join(f'<li><span class="when">{esc(w["when"])}</span><span class="what"><span class="title">{esc(w["what"])}</span>'
                   f'<span class="sub">{esc(w["where"])}</span></span></li>' for w in d["work"])
    honors = "".join(f'<li><span class="when">{esc(h["when"])}</span><span class="what">{esc(h["text"])}</span></li>'
                     for h in d["honors"])

    body = f"""
<section class="intro">
  {me}
  {paras(site, d['intro'])}
</section>

<h2 id="now">Now</h2>
<ul class="dash">{now}</ul>

<h2 id="projects">Projects</h2>
<div class="strip">{strip}</div>
<ul class="rows">{main_rows}</ul>
<h3>Smaller things</h3>
<ul class="rows compact">{small_rows}</ul>

<h2 id="about">How I got here</h2>
{paras(site, d['about'])}

<h2 id="work">Work</h2>
<ul class="rows compact">{work}</ul>

<h2 id="results">Results</h2>
<ul class="rows compact">{honors}</ul>

<h2 id="other">Other things</h2>
{paras(site, d['other'])}

<h2 id="contact">Contact</h2>
<p>{inline(site, d['contact'])}</p>
"""
    page = shell(site, title=f"{d['name']} (notazizelse)", description=d["description"], body=body,
                 canonical=site.home(), og_image=site.home(f"img/{photo['full']}"), home_nav=True)
    (out / "index.html").write_text(page, encoding="utf-8")


# ------------------------------------------------------------ project pages

def human_size(n):
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{max(1, round(n / 1e3))} KB"


def copy_app(app, out):
    src = Path(app["src"])
    target = out / app["path"]
    if src.is_file():
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target / "index.html")
        return
    if not src.is_dir():
        sys.exit(f"missing app src: {src}")
    patterns = SKIP + app.get("exclude", [])
    shutil.copytree(src, target, dirs_exist_ok=True,
                    ignore=lambda _d, names: [n for n in names if any(fnmatch.fnmatch(n, pat) for pat in patterns)])
    if not (target / "index.html").exists():
        sys.exit(f"app {src} has no index.html")


def doc_src(p, doc):
    s = Path(doc["src"])
    if s.is_absolute():
        return s
    return Path(p["root"]) / s if p.get("root") else ROOT / s


def render_project(site, p, out):
    d = site.data
    slug = p["slug"]
    img_dir = out / "img"
    repo, private = p.get("repo"), p.get("private", False)

    doc_map = {}   # source path -> doc page name, so docs can link to each other
    for doc in p.get("docs", []):
        src = doc_src(p, doc).resolve()
        if not src.exists():
            sys.exit(f"missing doc: {src}")
        doc_map[str(src)] = doc["name"]

    actions = []
    if p.get("app"):
        a = p["app"]
        copy_app(a, out)
        actions.append(f'<a class="go" href="/{a["path"]}/{esc(a.get("open", ""))}">{esc(a["label"])} →</a>')
    if p.get("live"):
        actions.append(f'<a class="go" href="{esc(p["live"]["url"])}">{esc(p["live"]["label"])} →</a>')
    for link in p.get("links", []):
        actions.append(f'<a href="{esc(link["url"])}">{esc(link["label"])}</a>')

    meta = " · ".join(x for x in (esc(p["year"]), esc(p.get("status", "")), esc(site.host(slug))) if x)
    parts = [f'<p class="back"><a href="{site.home()}#projects">← all projects</a></p>',
             f"<h1>{esc(p['title'])}</h1>",
             f'<p class="meta">{meta}</p>',
             f'<div class="lead">{paras(site, p["lead"])}</div>']
    if actions:
        parts.append(f'<p class="actions">{"".join(actions)}</p>')

    og = None
    if p.get("cover"):
        c = p["cover"]
        v = image(c["src"], img_dir)
        og = site.sub(slug, f"img/{v['full']}")
        wide = v["w"] / v["h"] > 1.3   # only landscape pictures get to break out of the text column
        parts.append(figure(c["src"], c["alt"], c.get("caption", ""), img_dir, cls="hero wide" if wide else "hero",
                            sizes="(min-width: 1000px) 920px, 100vw" if wide else "(min-width: 760px) 700px, 100vw"))
    if p.get("diagram"):
        parts.append(f'<pre class="diagram" aria-label="How the parts connect">{esc(p["diagram"])}</pre>')

    if p.get("facts"):
        rows = "".join(f"<dt>{esc(k)}</dt><dd>{inline(site, v)}</dd>" for k, v in p["facts"])
        parts.append(f'<h2>At a glance</h2><dl class="specs">{rows}</dl>')

    for s in p.get("body", []):
        parts.append(f"<h2>{esc(s['h'])}</h2>")
        parts.append(paras(site, s.get("p", [])))
        if s.get("list"):
            parts.append('<ul class="dash">' + "".join(f"<li>{inline(site, x)}</li>" for x in s["list"]) + "</ul>")

    if p.get("readme"):
        src = ROOT / p["readme"]
        parts.append('<h2>From the README</h2><div class="prose">' +
                     render_md(src.read_text(encoding="utf-8"), md_dir=src.parent, out_root=out, repo=repo,
                               private=private, root=src.parent) + "</div>")

    if p.get("gallery"):
        figs = "".join(figure(g["src"], g["alt"], g.get("caption", ""), img_dir, cls="full" if g.get("full") else "",
                              sizes="(min-width: 760px) 700px, 100vw" if g.get("full") else "(min-width: 760px) 340px, 100vw")
                       for g in p["gallery"])
        parts.append(f'<h2>Pictures</h2><div class="gallery">{figs}</div>')

    if p.get("docs"):
        items = ""
        for doc in p["docs"]:
            desc = f'<span class="desc">{esc(doc["desc"])}</span>' if doc.get("desc") else ""
            items += f'<li><a href="/docs/{doc["name"]}/">{esc(doc["title"])}</a>{desc}</li>'
            render_doc(site, p, doc, out, doc_map)
        parts.append(f'<h2>Documents</h2><ul class="files">{items}</ul>')

    if p.get("files"):
        (out / "files").mkdir(parents=True, exist_ok=True)
        items = ""
        for f in p["files"]:
            src = Path(f["src"])
            if not src.exists():
                sys.exit(f"missing file: {src}")
            shutil.copy2(src, out / "files" / f["name"])
            desc = f'<span class="desc">{esc(f["desc"])}</span>' if f.get("desc") else ""
            items += (f'<li><a href="/files/{esc(f["name"])}" download>{esc(f["label"])}</a>'
                      f'<span class="size">{esc(f["name"])} · {human_size(src.stat().st_size)}</span>{desc}</li>')
        parts.append(f'<h2>Downloads</h2><ul class="files">{items}</ul>')

    if repo and private:
        parts.append('<p class="credit">The code is in a private repository for now.</p>')
    if p.get("credit"):
        parts.append(f'<p class="credit">{inline(site, p["credit"])}</p>')

    lead = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", p["lead"][0])
    page = shell(site, title=f"{p['title']} · {d['name']}", description=lead[:300], body="\n".join(parts),
                 canonical=site.sub(slug), og_image=og)
    (out / "index.html").write_text(page, encoding="utf-8")


def render_doc(site, p, doc, out, doc_map):
    src = doc_src(p, doc)
    repo = doc.get("repo", p.get("repo"))
    root = doc.get("root", p.get("root"))
    private = p.get("private", False)
    body = render_md(src.read_text(encoding="utf-8"), md_dir=src.parent, out_root=out, repo=repo,
                     private=private, root=root, doc_map=doc_map)
    where = ""
    if repo and not private and root:
        try:
            rel = src.resolve().relative_to(Path(root).resolve()).as_posix()
            where = f' · <a href="https://github.com/{repo}/blob/HEAD/{rel}">{esc(rel)} on GitHub</a>'
        except ValueError:
            pass
    page_body = (f'<p class="back"><a href="/">← {esc(p["title"])}</a></p>'
                 f'<h1>{esc(doc["title"])}</h1><p class="meta">{esc(site.host(p["slug"]))}{where}</p>'
                 f'<article class="prose">{body}</article>')
    target = out / "docs" / doc["name"]
    target.mkdir(parents=True, exist_ok=True)
    page = shell(site, title=f"{doc['title']} · {p['title']}", description=doc.get("desc", doc["title"]),
                 body=page_body, canonical=site.sub(p["slug"], f"docs/{doc['name']}/"))
    (target / "index.html").write_text(page, encoding="utf-8")


def render_404(site, out):
    body = f"""<div class="lost">
<h1>Nothing here</h1>
<p>This page doesn't exist, or I haven't made it yet.</p>
<p><a href="{site.home()}">Go to the home page</a> or <a href="{site.home()}#projects">see all projects</a>.</p>
</div>"""
    page = shell(site, title="Not found · notazizelse", description="Page not found.", body=body, canonical=site.home())
    # Also served for unknown subdomains, so its CSS and icon come from the apex.
    page = page.replace('href="/static/', f'href="{site.home()}static/')
    (out / "404.html").write_text(page, encoding="utf-8")


def render_extras(site, out):
    urls = [site.home()] + [site.sub(p["slug"]) for p in site.projects]
    sm = "".join(f"<url><loc>{esc(u)}</loc></url>" for u in urls)
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                     f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>\n', encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site.home('sitemap.xml')}\n", encoding="utf-8")


# ------------------------------------------------------------ checks + bundle

REF_RE = re.compile(r'(?:href|src)="([^"]+)"|srcset="([^"]+)"')


def check_links(site_roots):
    """Every relative link in the generated pages must point at a file that exists (apps aren't checked)."""
    bad = []
    for root, pages in site_roots:
        for f in pages:
            for m in REF_RE.finditer(f.read_text(encoding="utf-8")):
                refs = [m.group(1)] if m.group(1) else [s.strip().split(" ")[0] for s in m.group(2).split(",")]
                for ref in refs:
                    ref = html.unescape(ref)
                    if re.match(r"^(?:[a-z]+:|//|#)", ref):
                        continue
                    path = unquote(ref.split("#")[0].split("?")[0])
                    target = (root / path.lstrip("/")) if path.startswith("/") else (f.parent / path)
                    if path.endswith("/") or target.is_dir():
                        target = target / "index.html"
                    if not target.exists():
                        bad.append(f"{f.relative_to(DIST)} -> {ref}")
    return bad


def bundle():
    out = DIST / "bundle.tgz"
    with tarfile.open(out, "w:gz", compresslevel=6) as tar:
        tar.add(PUBLIC, arcname="public")
        for name in ("server.py", "sitectl"):
            info = tar.gettarinfo(str(ROOT / "server" / name), arcname=name)
            info.mode = 0o755
            with open(ROOT / "server" / name, "rb") as fh:
                tar.addfile(info, fh)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true", help="links point at *.localhost:8795")
    ap.add_argument("--bundle", action="store_true", help="also write dist/bundle.tgz")
    args = ap.parse_args()
    if args.dev and args.bundle:
        sys.exit("--bundle is for production builds only")

    site = Site(dev=args.dev)
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    apex = PUBLIC / "apex"
    write_static(apex / "static")
    render_home(site, apex)
    render_404(site, apex)
    render_extras(site, apex)
    roots = [(apex, [apex / "index.html"])]
    for p in site.projects:
        out = PUBLIC / "p" / p["slug"]
        write_static(out / "static")
        render_project(site, p, out)
        roots.append((out, [out / "index.html"] + sorted((out / "docs").glob("*/index.html"))))

    bad = check_links(roots)
    if bad:
        print("broken links:\n  " + "\n  ".join(bad))
        sys.exit(1)
    size = sum(f.stat().st_size for f in PUBLIC.rglob("*") if f.is_file())
    ndocs = sum(len(p.get("docs", [])) for p in site.projects)
    print(f"built {'dev' if args.dev else 'prod'}: home + {len(site.projects)} project subdomains, "
          f"{ndocs} documents, {size / 1e6:.1f} MB")
    if args.bundle:
        print(f"bundle: {bundle()} ({(DIST / 'bundle.tgz').stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
