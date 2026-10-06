# notazizelse.xyz

My personal site, laid out like a component datasheet (part number AZB-12). The home page is **https://notazizelse.xyz**, and every project has its own subdomain at **https://[project].notazizelse.xyz** with photos, specs, its documents and downloads.

## How it's put together

| Path | What it is |
|---|---|
| `content/site.json` | Home page text: intro, now, story, work, results, contact |
| `content/projects.json` | One entry per project. Each one becomes `<slug>.notazizelse.xyz` |
| `content/repos/` | READMEs of GitHub-only projects, fetched by `tools/fetch_readmes.py` |
| `content/shots/` | Screenshots of apps that had none |
| `build.py` | Builds everything into `dist/public` (Python, Pillow, Markdown) |
| `static/styles.css`, `static/site.js` | The stylesheet, and the script for the 16×2 LCD on the home page |
| `static/art/` | Technical drawings for projects that have no photos |
| `server/server.py` | Static server that picks a folder by hostname (standard library only) |
| `server/sitectl` | Controls the site on the VM: start, stop, status, install, tunnel, cron |
| `deploy/deploy.ps1` | Build, upload and go live |

A project entry can have any of these keys:
- `lead` (intro paragraphs)
- `cover`, `gallery` (pictures)
- `facts` (the "At a glance" table)
- `body` (sections)
- `readme` (render a README as the body)
- `docs` (markdown files, each rendered as a page under `/docs/<name>/`)
- `files` (downloads under `/files/`)
- `links`
- `app` (a static app copied to a subpath like `/play/`)
- `live` (link to an app hosted somewhere else)

Relative links inside docs turn into links to the file on GitHub, so `repo` and `root` (the local folder that matches the repo) should be set.

## Day to day

```powershell
python build.py --dev
python server/server.py --root dist/public --domain localhost --port 8795
#   then open http://localhost:8795 and http://camp.localhost:8795
.\deploy\deploy.ps1
```

Put the SSH target (`user@host`) in `deploy\target.txt`, which is ignored by git. Another option is to set `NOTAZIZELSE_SSH`.

To add a project, add an entry to `content/projects.json` and deploy. The `*.notazizelse.xyz` wildcard record already points at this site's tunnel, so there's no DNS step. A project that needs its own backend runs as its own process with its own tunnel. Its specific DNS record wins over the wildcard. For example, glasses4dyslexic is live at its own subdomain, and its write-up is at `glasses.notazizelse.xyz`.

## On the VM (`~/site`)

```
public/         the live site (public.old is the previous deploy)
server.py       python3 on 127.0.0.1:8795
sitectl         status | logs [app|tunnel] | restart | routes | ...
bin/cloudflared this site's own copy
cf/             tunnel credentials (secret)
```

- The `notazizelse-site` tunnel serves `notazizelse.xyz` and `*.notazizelse.xyz`.
- Cron runs `sitectl start` at boot and `sitectl ensure` every 2 minutes.

## Type

- [Departure Mono](https://departuremono.com) by Helena Zhang and Tobias Fried (OFL), for part numbers, labels and the LCD glyphs.
- [Atkinson Hyperlegible Next and Mono](https://www.brailleinstitute.org/freefont/) by the Braille Institute (OFL), for reading. It's the same family the glasses project's reading screen offers.
