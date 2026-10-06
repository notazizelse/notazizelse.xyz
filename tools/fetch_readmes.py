#!/usr/bin/env python3
"""Download repo info (languages with byte counts, top-level files, stars, dates) for every public project repo,
plus the README and the images it references for GitHub-only projects. Everything goes into content/repos/<repo>/.

    python tools/fetch_readmes.py            (needs the gh CLI, logged in)
Re-run whenever a repo changes; the site build only reads the local copies.
"""
import base64, json, re, subprocess, sys
from pathlib import Path

OWNER = "notazizelse"
# GitHub-only projects: their README becomes the body of the project page.
README_REPOS = ["limitio", "GPS-Tracker", "complexio", "macropad", "haven-tashkent_bot",
                "STM32_homebrew_fix_script_for_mac", "lesson_descriptor", "Synchronizer", "anki-listen-mode", "jumpio"]
# Projects with local folders: only the repo panel (languages + files) is needed.
META_REPOS = ["camp", "haven-hub", "haven-pcb-badges", "Orbita26", "WiT", "KarateFC", "vocabio", "haven-tashkent-team"]
OUT = Path(__file__).resolve().parent.parent / "content" / "repos"


def gh(*args):
    return subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True).stdout


def fetch_meta(repo):
    info = json.loads(gh(f"repos/{OWNER}/{repo}"))
    if info.get("private"):
        sys.exit(f"{repo} is private; it must not be published")
    meta = {k: info.get(k) for k in ("description", "language", "html_url", "default_branch", "created_at",
                                    "pushed_at", "stargazers_count", "license")}
    if meta["license"]:
        meta["license"] = meta["license"].get("spdx_id")
    meta["languages"] = json.loads(gh(f"repos/{OWNER}/{repo}/languages"))   # {name: bytes}
    files = json.loads(gh(f"repos/{OWNER}/{repo}/contents"))
    meta["files"] = sorted(([f["name"], f["type"]] for f in files), key=lambda f: (f[1] != "dir", f[0].lower()))
    meta["commits"] = len(json.loads(gh(f"repos/{OWNER}/{repo}/commits?per_page=100")))
    return meta


def fetch_readme(repo, d):
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
    return len(text), got


for repo in README_REPOS + META_REPOS:
    d = OUT / repo
    d.mkdir(parents=True, exist_ok=True)
    meta = fetch_meta(repo)
    (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8", newline="\n")
    note = ""
    if repo in README_REPOS:
        chars, imgs = fetch_readme(repo, d)
        note = f", README {chars} chars, {imgs} images"
    print(f"{repo}: {meta['commits']} commits, langs {list(meta['languages'])}{note}")
