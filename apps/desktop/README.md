# CARA Desktop

Native desktop wrapper for CARA — Windows + Linux. Built with Tauri 2
(Rust + system webview). The whole binary is ~8 MB and starts in well
under a second; it loads the home backend in a slim native window so
you get a real Start-menu entry / `.desktop` launcher and a system
tray icon, without the awkward "install web app" step the browser
shows.

Implementing the UI natively (Qt, raw GTK, etc.) would mean rewriting
every React page in C++ — months of work for the same end-user feel.
Tauri keeps the existing PWA as-is and bundles only the shell.

## Where to get installers

Every push to `main` that touches `apps/desktop/**` triggers the
`desktop · build` workflow, which produces:

| Target              | Artifact                                 |
| ------------------- | ---------------------------------------- |
| Windows x86_64      | `cara-desktop-windows-x86_64/*.msi`      |
| Linux x86_64 (AppImage) | `cara-desktop-linux-x86_64/*.AppImage` |
| Linux x86_64 (Debian/Ubuntu) | `cara-desktop-linux-x86_64/*.deb` |

Tagging `desktop-vX.Y.Z` also drafts a GitHub Release with the same
files attached, so the family can grab the latest installer without
needing GitHub Actions access.

## Install

### Windows

1. Download the `.msi` from the latest desktop-v* release (or from the
   workflow artefacts page).
2. Double-click. The installer is unsigned, so Windows SmartScreen will
   warn about an "unknown publisher" — click **More info** → **Run
   anyway**. (Signing requires an EV certificate we don't have yet.)
3. CARA appears in the Start menu and a system tray icon.

### Linux — AppImage

```sh
chmod +x CARA-*.AppImage
./CARA-*.AppImage
```

For a permanent install drop it into `~/Applications/` and create a
`.desktop` file (the AppImage launches with `--install` to do this
automatically on most distros).

### Linux — .deb

```sh
sudo apt install ./cara-desktop_*.deb
```

Dependencies (`libwebkit2gtk-4.1-0`, `libgtk-3-0`) are pulled in by
the package manager.

## First run

The window opens at `https://192.168.1.23:8455` by default — your home
backend. From outside the LAN you'll need either:

- WireGuard up (10.8.0.0/24 still hits the same URL)
- or a Cloudflare Tunnel pointing to the backend (then edit the URL
  via the launcher, see *Changing the backend URL* below)

The home backend uses a self-signed certificate (mkcert CA). On first
launch the webview will refuse to connect; trust the CA the same way
you do in Chrome:

- **Windows**: import `cara-rootCA.crt` into *Trusted Root Certification
  Authorities* (the backend serves it at
  `https://192.168.1.23:8455/cara-rootCA.crt`).
- **Linux**: drop the same CA into `/usr/local/share/ca-certificates/`
  and run `sudo update-ca-certificates`.

## Changing the backend URL

Edit `src-tauri/tauri.conf.json`, change `app.windows[0].url`, rebuild.
A runtime-configurable URL is on the to-do — it's currently baked into
the binary so the family can't get the URL wrong by accident.

## Local development

You need Rust + Node 20 + the platform's webview dev libs (see the CI
workflow for the Ubuntu apt list). Then:

```sh
cd apps/desktop
npm install
npm run dev    # opens a hot-reloading window pointed at the dev URL
npm run build  # produces installers in src-tauri/target/release/bundle/
```

Building on the NanoPC (aarch64) works but is slow and consumes ~3 GB
of disk in `src-tauri/target/`. Cross-builds for Windows + Linux
x86_64 are best done in CI.
