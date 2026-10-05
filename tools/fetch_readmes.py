#!/usr/bin/env python3
"""Download README + the images it references + repo info for GitHub-only projects, into content/repos/<repo>/.

    python tools/fetch_readmes.py            (needs the gh CLI, logged in)
Re-run whenever one of those READMEs changes; the site build only reads the local copies.
"""
import base64, json, re, subprocess, sys
from pathlib import Path

OWNER = "notazizelse"
REPOS = ["limitio", "GPS-Tracker", "complexio", "macropad", "haven-tashkent_bot",
         "STM32_homebrew_fix_script_for_mac", "lesson_descriptor", "Synchronizer", "anki-listen-mode", "jumpio"]
OUT = Path(__file__).resolve().parent.parent / "content" / "repos"


def gh(*args):
    return subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True).stdout


for repo in REPOS:
    d = OUT / repo
    d.mkdir(parents=True, exist_ok=True)
    info = json.loads(gh(f"repos/{OWNER}/{repo}"))
    meta = {k: info.get(k) for k in ("description", "language", "html_url", "default_branch", "created_at", "pushed_at", "private")}
    langs = json.loads(gh(f"repos/{OWNER}/{repo}/languages"))
    meta["languages"] = list(langs)
    files = json.loads(gh(f"repos/{OWNER}/{repo}/contents"))
    meta["files"] = [f["name"] for f in files]
    readme = json.loads(gh(f"repos/{OWNER}/{repo}/readme"))
    text = base64.b64decode(readme["content"]).decode("utf-8", "replace")
    (d / "README.md").write_text(text, encoding="utf-8", newline="\n")
    got = 0
    for m in re.finditer(r'!\[[^\]]*\]\(([^)\s]+)|<img[^>]+src="([^"]+)"', text):
        ref = m.group(1) or m.group(2)
        if re.match(r"^[a-z]+:", ref) or ref.startswith("//"):
            continue
        path = ref.lstrip("./")
        try:
            blob = json.loads(gh(f"repos/{OWNER}/{repo}/contents/{path}"))
            (d / path).parent.mkdir(parents=True, exist_ok=True)
            (d / path).write_bytes(base64.b64decode(blob["content"]))
            got += 1
        except subprocess.CalledProcessError:
            print(f"  {repo}: could not fetch image {ref}", file=sys.stderr)
    (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8", newline="\n")
    print(f"{repo}: README {len(text)} chars, {got} images, langs {meta['languages']}")
