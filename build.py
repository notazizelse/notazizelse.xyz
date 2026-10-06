#!/usr/bin/env python3
"""Build notazizelse.xyz: a personal site laid out like a component datasheet.

    python build.py            production build -> dist/public   (links use https://<slug>.notazizelse.xyz)
    python build.py --dev      local build                        (links use http://<slug>.localhost:8795)
    python build.py --bundle   production build + dist/bundle.tgz for deploy/deploy.ps1

Output (what ~/site/public looks like on the server):
    apex/                 notazizelse.xyz: the "datasheet"
    p/<slug>/             <slug>.notazizelse.xyz: an "application note" with img/, files/, docs/<name>/ and the app if any
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
FONTS = ("https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Mono:wght@400;600"
         "&family=Atkinson+Hyperlegible+Next:ital,wght@0,400;0,700;1,400&display=swap")
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
        for i, p in enumerate(self.projects, 1):
            if not SLUG_RE.match(p["slug"]) or p["slug"] in seen or p["slug"] == "www":
                sys.exit(f"bad or duplicate slug: {p['slug']}")
            seen.add(p["slug"])
            p["_ref"] = f"U{i}"           # reference designator on the home page
            p["_an"] = f"AN-{i:02d}"      # application note number on its own page
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


def plain(text):
    return LINK_RE.sub(r"\1", text)


# ------------------------------------------------------------ images

def image(src, out_dir, name=None, widths=(1600, 760)):
    """Resize src into out_dir as webp (cached in .cache/img). SVGs are copied as they are."""
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


def fig_img(src, alt, out_dir, sizes, url_prefix="/img/", loading="lazy"):
    v = image(src, out_dir)
    return (f'<a class="frame" href="{url_prefix}{v["full"]}"><img src="{url_prefix}{v["small"]}" '
            f'srcset="{url_prefix}{v["small"]} 760w, {url_prefix}{v["full"]} {v["w"]}w" sizes="{sizes}" '
            f'width="{v["w"]}" height="{v["h"]}" alt="{esc(alt)}" loading="{loading}"></a>'), v


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

def shell(site, *, title, description, body, canonical, og_image=None, left=None, nav=None, page_label=None, script=False):
    d = site.data
    left = left or f'<a class="mark" href="{site.home()}"><span class="chip" aria-hidden="true"></span>{esc(d["part"])}</a>'
    nav = nav or (f'<a href="{site.home()}#applications">projects</a><a href="{site.home()}#detailed">about</a>'
                  f'<a href="{site.home()}#pins">contact</a>')
    og = f'\n<meta property="og:image" content="{esc(og_image)}">' if og_image else ""
    js = '\n<script src="/static/site.js" defer></script>' if script else ""
    label = page_label or f'{esc(d["docnum"])} – {esc(d["date"])}'
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
<meta name="theme-color" content="#14532d">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="/static/styles.css">{js}
</head>
<body>
<div class="sheet">
<header class="runhead">
  {left}
  <nav>{nav}</nav>
  <span>{label}</span>
</header>
<main>
{body}
</main>
<footer class="legal">
  <span>Copyright © 2026, {esc(d['name'])}</span>
  <span><a href="mailto:{esc(d['email'])}?subject=Feedback%20on%20{esc(d['part'])}">Submit document feedback</a></span>
  <span>Source: <a href="https://github.com/notazizelse/notazizelse.xyz">github.com/notazizelse/notazizelse.xyz</a></span>
</footer>
</div>
</body>
</html>
"""


def favicon():
    # A DIP chip, seen from above.
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#14532d"/>'
            '<rect x="9" y="6" width="14" height="20" rx="1.5" fill="#15140f"/>'
            '<path d="M6 9h3M6 13h3M6 17h3M6 21h3M23 9h3M23 13h3M23 17h3M23 21h3" stroke="#c58b2b" stroke-width="2"/>'
            '<circle cx="12" cy="9" r="1.2" fill="#8a8a8a"/></svg>')


def write_static(dest, with_js=False):
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(STATIC / "styles.css", dest / "styles.css")
    if with_js:
        shutil.copy2(STATIC / "site.js", dest / "site.js")
    (dest / "favicon.svg").write_text(favicon(), encoding="utf-8")


def h2(num, text, anchor=None):
    a = f' id="{anchor}"' if anchor else ""
    return f'<h2 class="sec"{a}><span class="num">{num}</span>{esc(text)}</h2>'


def h3(num, text, anchor=None):
    a = f' id="{anchor}"' if anchor else ""
    return f'<h3 class="sub"{a}><span class="num">{num}</span>{esc(text)}</h3>'


def table(caption_num, caption, head, rows, numeric=(), raw=False, cls="dt"):
    """rows are lists of cells; numeric = column indexes to centre; raw = cells are already HTML."""
    th = "".join(f'<th{" class=n" if i in numeric else ""}>{esc(h)}</th>' for i, h in enumerate(head))
    body = ""
    for r in rows:
        tds = ""
        for i, c in enumerate(r):
            cls_attr = ' class="n"' if i in numeric else ""
            tds += f"<td{cls_attr}>{c if raw else esc(c)}</td>"
        body += f"<tr>{tds}</tr>"
    cap = f"<caption><b>Table {caption_num}.</b>{esc(caption)}</caption>" if caption else ""
    return f'<div class="tw"><table class="{cls}">{cap}<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def pagebreak(site, page):
    d = site.data
    return (f'<div class="pagebreak"><span>{esc(d["part"])} · {esc(d["docnum"])} – {esc(d["date"])}</span>'
            f'<span><a href="mailto:{esc(d["email"])}">Submit document feedback</a></span><span class="pg">{page}</span></div>')


# ------------------------------------------------------------ figures drawn in code

SCH = {"wire": "#008400", "body": "#840000", "fill": "#ffffc2", "pinname": "#008484", "pinnum": "#840000",
       "ref": "#008484", "sheet": "#840084", "text": "#15140f"}
SVG_FONT = "font-family=\"'Atkinson Hyperlegible Mono', Consolas, monospace\""


def schematic_svg(site):
    """'Figure 3-1. Simplified schematic': what I'm doing now, drawn in KiCad's classic colours."""
    c = SCH
    now = site.data["now"]
    o = [f'<svg viewBox="0 0 900 430" role="img" aria-label="Schematic: the AZB-12 connected to what I am working on now" {SVG_FONT} font-size="13">']
    o.append('<rect width="900" height="430" fill="#f7f5ee"/>')
    # body
    o.append(f'<rect x="360" y="90" width="180" height="250" fill="{c["fill"]}" stroke="{c["body"]}" stroke-width="2.5"/>')
    o.append(f'<text x="366" y="80" fill="{c["ref"]}">U1</text>')
    o.append(f'<text x="450" y="222" text-anchor="middle" font-size="20" fill="{c["body"]}" style="font-family:\'Departure Mono\',monospace">AZB-12</text>')
    o.append(f'<text x="450" y="244" text-anchor="middle" font-size="11" fill="{c["ref"]}">Azizbek N.</text>')
    # pins: 1,2 left (top-down), 3,4 right (bottom-up)
    ys = {1: 150, 2: 285, 3: 285, 4: 150}
    for item in now:
        n = item["pin"]
        y = ys[n]
        left = n <= 2
        x0, x1 = (360, 320) if left else (540, 580)
        o.append(f'<path d="M{x0} {y}H{x1}" stroke="{c["body"]}" stroke-width="2"/>')
        o.append(f'<text x="{(x0 + x1) / 2}" y="{y - 6}" text-anchor="middle" font-size="11" fill="{c["pinnum"]}">{n}</text>')
        o.append(f'<text x="{x0 + 8 if left else x0 - 8}" y="{y + 4}" text-anchor="{"start" if left else "end"}" fill="{c["pinname"]}">{esc(item["net"])}</text>')
        # wire to the hierarchical sheet
        sx = 268 if left else 632
        o.append(f'<path d="M{x1} {y}H{sx}" stroke="{c["wire"]}" stroke-width="2"/>')
        o.append(f'<text x="{(x1 + sx) / 2}" y="{y - 7}" text-anchor="middle" font-size="11" fill="{c["text"]}">{esc(item["net"])}</text>')
        bx = 30 if left else 640
        box = (f'<rect x="{bx}" y="{y - 38}" width="230" height="76" fill="#ffffff" fill-opacity=".55" stroke="{c["sheet"]}" stroke-width="2"/>'
               f'<path d="{"M260 %d l8 -6 v12 z" % y if left else "M640 %d l-8 -6 v12 z" % y}" fill="{c["sheet"]}"/>'
               f'<text x="{bx}" y="{y - 44}" font-size="11" fill="{c["sheet"]}">Sheet: {esc(item["net"])}</text>'
               f'<text x="{bx + 12}" y="{y - 10}" font-weight="600" font-size="15" fill="{c["text"]}">{esc(item["title"])}</text>'
               f'<text x="{bx + 12}" y="{y + 12}" font-size="12.5" fill="#5d594f">{esc(item["role"])}</text>'
               f'<text x="{bx}" y="{y + 52}" font-size="11" fill="{c["sheet"]}">File: {esc(item["net"].lower())}.kicad_sch</text>')
        if item.get("slug"):
            box = f'<a href="{site.sub(item["slug"])}">{box}</a>'
        o.append(box)
    # VCC + decoupling cap, GND
    o.append(f'<path d="M450 90V50" stroke="{c["body"]}" stroke-width="2"/><text x="456" y="80" font-size="11" fill="{c["pinnum"]}">5</text>')
    o.append(f'<path d="M440 36H460M450 36V50" stroke="{c["text"]}" stroke-width="2"/><text x="450" y="28" text-anchor="middle" font-size="12">VCC</text>')
    o.append(f'<path d="M450 50H600V68M600 82V104" stroke="{c["wire"]}" stroke-width="2" fill="none"/><circle cx="450" cy="50" r="4" fill="{c["wire"]}"/>')
    o.append(f'<path d="M586 68H614M586 82H614" stroke="{c["body"]}" stroke-width="2.5"/>')
    o.append(f'<text x="622" y="72" font-size="11" fill="{c["ref"]}">C1</text><text x="622" y="86" font-size="11" fill="{c["ref"]}">100n</text>')
    o.append(f'<path d="M590 104H610M594 109H606M598 114H602" stroke="{c["text"]}" stroke-width="2"/>')
    o.append(f'<path d="M450 340V380" stroke="{c["body"]}" stroke-width="2"/><text x="456" y="356" font-size="11" fill="{c["pinnum"]}">6</text>')
    o.append(f'<path d="M438 380H462M443 386H457M448 392H452" stroke="{c["text"]}" stroke-width="2"/>')
    o.append(f'<text x="882" y="418" text-anchor="end" font-size="11" fill="#5d594f">File: now.kicad_sch · Rev G</text>')
    o.append("</svg>")
    return "".join(o)


def pinout_svg(site):
    """'Figure 5-1. Pinout': a DIP-16 seen from the top; the pins are links."""
    pins = {p["n"]: p for p in site.data["pins"]}
    o = [f'<svg class="pinout" viewBox="0 0 560 600" role="img" aria-label="DIP-16 pinout. Each pin links somewhere." {SVG_FONT} font-size="15">']
    o.append('<rect width="560" height="600" fill="#f7f5ee"/>')
    o.append('<rect x="200" y="50" width="160" height="500" rx="4" fill="#1b1b1b"/>')
    o.append('<path d="M262 50a18 18 0 0 0 36 0z" fill="#f7f5ee"/>')
    o.append('<circle cx="222" cy="78" r="6" fill="#3a3a3a"/>')
    o.append('<text x="280" y="300" text-anchor="middle" fill="#d6d3cb" font-size="26" transform="rotate(-90 280 300)" style="font-family:\'Departure Mono\',monospace">AZB-12</text>')
    o.append('<text x="314" y="300" text-anchor="middle" fill="#8f8c84" font-size="12" transform="rotate(-90 314 300)">notazizelse · 2026</text>')
    for i in range(8):
        y = 92 + i * 56
        for n, left in ((i + 1, True), (16 - i, False)):
            p = pins[n]
            px = 168 if left else 360
            num_x = 214 if left else 346
            lbl_x = 156 if left else 404
            anchor = "end" if left else "start"
            g = (f'<rect class="pin" x="{px}" y="{y - 9}" width="32" height="18" rx="2" fill="#c9c9c9" stroke="#8f8f8f"/>'
                 f'<text x="{num_x}" y="{y + 5}" text-anchor="{"start" if left else "end"}" fill="#8f8c84" font-size="12">{n}</text>'
                 f'<text class="lbl" x="{lbl_x}" y="{y + 5}" text-anchor="{anchor}" fill="#15140f" style="font-family:\'Departure Mono\',monospace">{esc(p["name"])}</text>')
            href = site.sub(p["slug"]) if p.get("slug") else p.get("url", "")
            if href:
                g = f'<a href="{esc(href)}"><title>{esc(p["desc"])}</title>{g}</a>'
            o.append(g)
    o.append('<text x="280" y="584" text-anchor="middle" fill="#5d594f" font-size="12">TOP VIEW · not to scale</text>')
    o.append("</svg>")
    return "".join(o)


# ------------------------------------------------------------ home: the datasheet

def render_home(site, out):
    d = site.data
    img_dir = out / "img"

    lcd_json = esc(json.dumps(d["lcd"]), quote=True)
    lcd = f"""<figure class="lcd" data-lcd="{lcd_json}">
  <div class="board">
    <span class="mh a"></span><span class="mh b"></span><span class="mh c"></span><span class="mh d"></span>
    <div class="holes" aria-hidden="true">{"<i></i>" * 16}</div>
    <div class="bezel" tabindex="0" role="img" aria-label="16 by 2 character LCD. It says: {esc(" ".join(d["lcd"][0]))}. Click it and type.">
      <canvas width="560" height="120"></canvas>
    </div>
    <div class="silk" aria-hidden="true"><span>LCD1 · 1602 · I²C</span><span>notazizelse@github</span></div>
    <input class="type-in" type="text" maxlength="32" autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="Type something to show on the LCD">
  </div>
  <figcaption><span><b>Figure 1.</b>The same 16×2 LCD as on CAMP v2. Click it and type.</span>
    <span class="btns"><button type="button" data-prev>SW1</button><button type="button" data-next>SW2</button></span></figcaption>
</figure>"""

    feats = "".join(f"<li>{inline(site, f)}</li>" for f in d["features"])
    apps = "".join(f'<li><a href="{site.sub(a["slug"])}">{esc(a["text"])}</a></li>' for a in d["applications"])
    devinfo = table("3-1", "Device information", ["Part number", "Package", "Body size (nom)"], d["device_info"])

    toc_items = [("1", "Features", "features", 1), ("2", "Applications", "apps-list", 1), ("3", "Description", "description", 1),
                 ("4", "Revision history", "revisions", 2), ("5", "Pin configuration and functions", "pins", 2),
                 ("6", "Specifications", "specs", 3), ("7", "Detailed description", "detailed", 4),
                 ("8", "Application and implementation", "applications", 5),
                 ("9", "Mechanical, packaging, and orderable information", "ordering", 6)]
    toc = "".join(f'<li><span class="n">{n}</span><a href="#{a}">{esc(t)}</a><span class="dots"></span><span class="pg">{pg}</span></li>'
                  for n, t, a, pg in toc_items)

    revisions = table("4-1", "", ["Date", "Rev", "Changes"], [[r[0], r[1], r[2]] for r in d["revisions"]], numeric=(1,))

    pin_rows = []
    for p in sorted(d["pins"], key=lambda p: p["n"]):
        href = site.sub(p["slug"]) if p.get("slug") else p.get("url", "")
        name = f'<a href="{esc(href)}">{esc(p["name"])}</a>' if href else esc(p["name"])
        pin_rows.append([name, str(p["n"]), esc(p["type"]), esc(p["desc"])])
    pin_table = table("5-1", "Pin functions", ["Name", "No.", "Type", "Description"], pin_rows, numeric=(1, 2), raw=True)

    ratings = table("6-1", "", ["Parameter", "Max", "Notes"], d["ratings"], numeric=(1,))
    conditions = table("6-2", "", ["Parameter", "Nominal"], d["conditions"])
    electrical = table("6-3", "", ["Parameter", "Test conditions", "Min", "Typ", "Max", "Unit"],
                       [[r[0], r[1], r[2] or "—", r[3], r[4], r[5]] for r in d["electrical"]], numeric=(2, 3, 4))
    results = table("6-4", "", ["Level", "Result"], d["results"])

    photo_html, photo = fig_img(d["photo"]["src"], d["photo"]["alt"], img_dir, "(min-width: 900px) 330px, 100vw")
    blocks = "".join(f'<li><span class="y">{esc(b[0])}</span><span class="t">{esc(b[1])}</span></li>' for b in d["blocks"])
    modes = "".join(f"<dt>{esc(m[0])}</dt><dd>{esc(m[1])}</dd>" for m in d["modes"])

    main = [p for p in site.projects if not p.get("small")]
    small = [p for p in site.projects if p.get("small")]
    cards = ""
    for i, p in enumerate(main, 1):
        src = (p.get("cover") or (p.get("gallery") or [{}])[0]).get("src")
        alt = (p.get("cover") or (p.get("gallery") or [{}])[0]).get("alt", p["title"])
        v = image(src, img_dir, widths=(900, 520))
        cards += (f'<figure class="app"><a class="shot" href="{site.sub(p["slug"])}">'
                  f'<img src="/img/{v["small"]}" width="{v["w"]}" height="{v["h"]}" alt="{esc(alt)}" loading="lazy">'
                  f'<span class="ref">{p["_ref"]}</span><span class="status">{esc(p.get("status", ""))}</span></a>'
                  f'<figcaption><span class="fno">Figure 8-{i} · {esc(p["year"])}</span>'
                  f'<span class="t"><a href="{site.sub(p["slug"])}">{esc(p["title"])}</a></span> {inline(site, p["short"])}'
                  f'<span class="host">{esc(site.host(p["slug"]))} →</span></figcaption></figure>')
    small_rows = [[f'<span class="code">{p["_ref"]}</span>', f'<a href="{site.sub(p["slug"])}">{esc(p["title"])}</a>',
                   inline(site, p["short"]), esc(p["year"])] for p in small]
    small_table = table("8-1", "Other applications", ["Ref", "Name", "Description", "Year"], small_rows, numeric=(3,), raw=True)

    body = f"""
<section class="title-row">
  <div>
    <h1 class="partno">{esc(d['part'])}</h1>
    <p class="title-long">{esc(d['part'])} {esc(d['title_long'])}</p>
    <p class="byline"><b>{esc(d['name'])}</b> · {esc(d['handle'])}<br>Tashkent, Uzbekistan · grade 12</p>
  </div>
  {lcd}
</section>

<section class="p1">
  <div>{h2("1", "Features", "features")}<ul class="bul">{feats}</ul></div>
  <div>{h2("2", "Applications", "apps-list")}<ul class="bul">{apps}</ul></div>
</section>

{h2("3", "Description", "description")}
<div class="desc-grid">
  <div>{paras(site, d['description'])}</div>
  <div>{devinfo}<p class="fn">(1) For everything else, see the orderable information at the end of the data sheet.</p></div>
</div>
<figure class="fig"><div class="frame">{schematic_svg(site)}</div>
  <figcaption><b>Figure 3-1.</b>Simplified schematic: what I'm working on right now</figcaption></figure>

<nav class="toc" aria-label="Table of contents"><h2>Table of Contents</h2><ol>{toc}</ol></nav>

{pagebreak(site, 2)}
{h2("4", "Revision History", "revisions")}
<p class="muted">Changes from the initial release (grade 6) to the current revision.</p>
{revisions}

{h2("5", "Pin Configuration and Functions", "pins")}
<div class="pins">
  <figure class="fig"><div class="frame">{pinout_svg(site)}</div><figcaption><b>Figure 5-1.</b>DIP-16 package, top view. The pins are links.</figcaption></figure>
  <div>{pin_table}</div>
</div>

{pagebreak(site, 3)}
{h2("6", "Specifications", "specs")}
{h3("6.1", "Absolute Maximum Ratings")}
<p class="muted">Measured, not estimated. Operation beyond these ratings has not been tested yet.</p>
{ratings}
{h3("6.2", "Recommended Operating Conditions")}
{conditions}
{h3("6.3", "Electrical Characteristics")}
{electrical}
{h3("6.4", "Test Results")}
{results}

{pagebreak(site, 4)}
{h2("7", "Detailed Description", "detailed")}
<div class="overview">
  <div>{h3("7.1", "Overview")}{paras(site, d['about'][:2])}</div>
  <figure class="fig">{photo_html}<figcaption><b>Figure 7-1.</b>{esc(d['photo']['caption'])}</figcaption></figure>
</div>
{h3("7.2", "Functional Block Diagram")}
<ol class="blocks">{blocks}</ol>
<p class="figcap" style="text-align:center;font-size:14px"><b style="font-family:var(--pixel);font-weight:400;color:var(--mask)">Figure 7-2.</b> Functional block diagram (in order of when each block was added)</p>
{h3("7.3", "Feature Description")}
<div class="an-body">{paras(site, d['about'][2:])}</div>
{h3("7.4", "Device Functional Modes")}
<dl class="modes">{modes}</dl>

{pagebreak(site, 5)}
{h2("8", "Application and Implementation", "applications")}
<p class="muted">Every application below has its own application note at <span style="font-family:var(--pixel)">[project].{esc(d['domain'])}</span>, with photos, documents and design files.</p>
<div class="apps">{cards}</div>
{h3("8.2", "Other Applications")}
{small_table}

{pagebreak(site, 6)}
{h2("9", "Mechanical, Packaging, and Orderable Information", "ordering")}
<p>{inline(site, d['contact'])}</p>
<div class="notice"><b>IMPORTANT NOTICE AND DISCLAIMER</b>
<p>This is a personal website, not a real data sheet. Every fact on it is real; the formatting is a joke I couldn't resist.
The AZB-12 is provided "as is" and occasionally loses at LEGO sumo.</p></div>
"""
    page = shell(site, title=f"{d['part']} · {d['name']} (notazizelse)", description=d["description_meta"] if "description_meta" in d else plain(d["description"][0]),
                 body=body, canonical=site.home(), og_image=site.home(f"img/{photo['full']}"), script=True,
                 nav='<a href="#applications">projects</a><a href="#detailed">about</a><a href="#revisions">history</a><a href="#pins">contact</a>')
    (out / "index.html").write_text(page, encoding="utf-8")


# ------------------------------------------------------------ project pages: application notes

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


def an_left(site, p):
    return (f'<a class="mark" href="{site.home()}"><span class="chip" aria-hidden="true"></span>{esc(site.data["part"])}</a>')


def render_project(site, p, out):
    d = site.data
    slug = p["slug"]
    img_dir = out / "img"
    repo, private = p.get("repo"), p.get("private", False)
    label = f'{p["_an"]} · {esc(site.host(slug))}'

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
    if p.get("docs"):
        actions.append('<a href="#documents">Technical documents</a>')
    if p.get("files"):
        actions.append('<a href="#design-files">Design files</a>')

    parts = [f'<p class="back"><a href="{site.home()}#applications">← {esc(d["part"])} data sheet</a></p>',
             f'<header class="an-head"><span class="kind">Application note {p["_an"]} · {p["_ref"]}</span>'
             f"<h1>{esc(p['title'])}</h1>"
             f'<span class="meta">{esc(p["year"])} · {esc(p.get("status", ""))} · {esc(site.host(slug))}</span></header>',
             f'<section class="abstract"><b>ABSTRACT</b>{paras(site, p["lead"])}</section>']
    if actions:
        parts.append(f'<nav class="actions" aria-label="Links">{"".join(actions)}</nav>')

    fig_n = 0
    og = None
    if p.get("cover"):
        c = p["cover"]
        fig_n += 1
        html_img, v = fig_img(c["src"], c["alt"], img_dir, "(min-width: 1120px) 1060px, 100vw", loading="eager")
        og = site.sub(slug, f"img/{v['full']}")
        parts.append(f'<figure class="fig an-wide">{html_img}<figcaption><b>Figure {fig_n}.</b>{esc(c.get("caption") or c["alt"])}</figcaption></figure>')

    sec = 0
    if p.get("facts"):
        sec += 1
        parts.append(h2(str(sec), "Key Specifications"))
        parts.append(table(f"{sec}-1", "", ["Parameter", "Value"], [[esc(k), inline(site, v)] for k, v in p["facts"]], raw=True))

    for s in p.get("body", []):
        sec += 1
        parts.append(h2(str(sec), s["h"]))
        body = paras(site, s.get("p", []))
        if s.get("list"):
            body += '<ul class="bul">' + "".join(f"<li>{inline(site, x)}</li>" for x in s["list"]) + "</ul>"
        parts.append(f'<div class="an-body">{body}</div>')

    if p.get("gallery"):
        sec += 1
        figs = ""
        for g in p["gallery"]:
            fig_n += 1
            full = g.get("full")
            html_img, _ = fig_img(g["src"], g["alt"], img_dir, "(min-width: 1120px) 1060px, 100vw" if full else "(min-width: 760px) 520px, 100vw")
            figs += (f'<figure class="fig{" full" if full else ""}">{html_img}'
                     f'<figcaption><b>Figure {fig_n}.</b>{esc(g.get("caption") or g["alt"])}</figcaption></figure>')
        parts.append(h2(str(sec), "Pictures"))
        parts.append(f'<div class="gallery">{figs}</div>')

    if p.get("readme"):
        sec += 1
        src = ROOT / p["readme"]
        parts.append(h2(str(sec), "From the README"))
        parts.append('<div class="prose">' + render_md(src.read_text(encoding="utf-8"), md_dir=src.parent, out_root=out,
                                                       repo=repo, private=private, root=src.parent) + "</div>")

    if p.get("docs"):
        sec += 1
        items = ""
        for doc in p["docs"]:
            desc = f'<span class="desc">{esc(doc["desc"])}</span>' if doc.get("desc") else ""
            items += f'<li><a href="/docs/{doc["name"]}/">{esc(doc["title"])}</a>{desc}</li>'
            render_doc(site, p, doc, out, doc_map)
        parts.append(h2(str(sec), "Technical Documents", "documents"))
        parts.append(f'<ul class="files">{items}</ul>')

    if p.get("files"):
        sec += 1
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
        parts.append(h2(str(sec), "Design Files", "design-files"))
        parts.append(f'<ul class="files">{items}</ul>')

    if repo and private:
        parts.append('<p class="credit">The code is in a private repository for now.</p>')
    if p.get("credit"):
        parts.append(f'<p class="credit">{inline(site, p["credit"])}</p>')

    page = shell(site, title=f"{p['title']} · {p['_an']} · {d['name']}", description=plain(p["lead"][0])[:300],
                 body="\n".join(parts), canonical=site.sub(slug), og_image=og, left=an_left(site, p), page_label=label)
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
    page_body = (f'<p class="back"><a href="/">← {p["_an"]} {esc(p["title"])}</a></p>'
                 f'<header class="an-head"><span class="kind">Technical document · {p["_an"]}</span>'
                 f'<h1>{esc(doc["title"])}</h1><span class="meta">{esc(site.host(p["slug"]))}{where}</span></header>'
                 f'<article class="prose" style="margin-top:22px">{body}</article>')
    target = out / "docs" / doc["name"]
    target.mkdir(parents=True, exist_ok=True)
    page = shell(site, title=f"{doc['title']} · {p['title']}", description=doc.get("desc", doc["title"]),
                 body=page_body, canonical=site.sub(p["slug"], f"docs/{doc['name']}/"), left=an_left(site, p),
                 page_label=f'{p["_an"]} · {esc(site.host(p["slug"]))}')
    (target / "index.html").write_text(page, encoding="utf-8")


def render_404(site, out):
    body = f"""<div class="lost">
<h1 class="partno">404</h1>
<p class="title-long">Errata: this page doesn't exist (yet).</p>
<p><a href="{site.home()}">Back to the {esc(site.data['part'])} data sheet</a> or <a href="{site.home()}#applications">see every project</a>.</p>
</div>"""
    page = shell(site, title="404 · notazizelse", description="Page not found.", body=body, canonical=site.home())
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
    write_static(apex / "static", with_js=True)
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
    print(f"built {'dev' if args.dev else 'prod'}: datasheet + {len(site.projects)} application notes, "
          f"{ndocs} documents, {size / 1e6:.1f} MB")
    if args.bundle:
        print(f"bundle: {bundle()} ({(DIST / 'bundle.tgz').stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
