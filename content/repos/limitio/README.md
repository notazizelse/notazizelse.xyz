# LimitIO

LimitIO is a Windows app that puts real daily time limits on specific websites (Instagram, YouTube, whatever your doomscroll of choice is) and specific applications (Telegram, Discord, games), enforced by a background service that a standard Windows account can't casually turn off - the same rough idea as iPhone Screen Time, adapted to what Windows actually lets you do.

**Read this before you rely on it.** LimitIO is *not* tamper-proof. It stops casual tampering - Task Manager, Services.msc, deleting config files, editing settings - by anyone using a standard (non-administrator) Windows account. It **cannot** stop someone signed in with an administrator account from disabling it, the same way iPhone Screen Time can ultimately be bypassed by erasing the device. If you want the strongest version of this, put the person being limited on a standard account and keep the admin account (and the LimitIO password) to yourself. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full, honest threat model.

## What it does

- **Per-website limits**: set a daily minutes budget for a domain (e.g. `instagram.com`, matching subdomains too). Detected via TLS SNI / plain HTTP Host header - no root certificate, no broken cert-pinning in other apps.
- **Per-app limits**: set a daily minutes budget for a process by name (e.g. `telegram`), regardless of what it's talking to.
- **A management password**, separate from your Windows password, gating rule changes, pausing monitoring, and changing the password itself. Viewing today's usage and using the daily one-minute "ignore" grace need no password - same as how Screen Time lets you see usage and tap "One More Minute" without its passcode.
- **One free 60-second bypass per limit per day** ("Ignore limit for 1 minute" in the tray menu), so a hard block never fully strands you mid-task.
- **A hardened Windows Service** running as SYSTEM that a standard account cannot stop, reconfigure, or delete via normal tools, with automatic crash recovery and a Scheduled-Task backstop.

## Install

Download the latest installer from this repository's [Releases page](../../releases), run it, click through the Windows SmartScreen "unknown publisher" warning (expected for a small unsigned open-source tool), and complete the first-run password setup. Full walkthrough: [docs/setup.md](docs/setup.md).

## Building from source

Requires the .NET 8 SDK on Windows (WPF/WinForms need the actual Windows Desktop SDK, so this doesn't build on Linux/macOS).

```powershell
dotnet build LimitIO.sln -c Release
dotnet test LimitIO.sln -c Release
```

To produce an installable package yourself, see [docs/RELEASING.md](docs/RELEASING.md).

## How it works

Architecture, data flow, the security model and its honest limits, and known accuracy trade-offs (Encrypted Client Hello, CDN-shared domains) are all in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

MIT - see [LICENSE](LICENSE).
