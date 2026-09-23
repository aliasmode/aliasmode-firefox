<p align="center">
  <img src="assets/brand/aliasmode.png" alt="AliasMode" width="120">
</p>

<h1 align="center">AliasMode Firefox</h1>

<p align="center">
  <strong>The anti-detect browser you can fully audit.</strong><br>
  A custom anti-detect Firefox browser, built on top of the Camoufox system.<br>
  Every fingerprint patch is public. No closed binary. No "trust us."
</p>

<p align="center">
  <a href="https://aliasmode.com/download/">Download AliasMode</a> ·
  <a href="https://github.com/aliasmode/aliasmode">AliasMode app</a> ·
  <a href="https://github.com/aliasmode/aliasmode-firefox/releases">Releases</a> ·
  <a href="#build-from-source">Build from source</a>
</p>

---

## What it is

AliasMode Firefox is the browser engine inside [AliasMode](https://aliasmode.com), the free, open-source browser profile manager. Each AliasMode profile runs in this engine with its own fingerprint, proxy, and storage.

Most anti-detect browsers ship a closed binary. You cannot check what it spoofs, what it leaks, or what it sends home. AliasMode Firefox is different: the engine, the patches, and the build pipeline are all in this repository under MPL-2.0.

## Why engine-level

Fingerprint protection happens in Firefox's C++ code, not in a JavaScript layer injected into the page. Pages cannot see it, hook it, or detect a patched API.

| | AliasMode Firefox | Typical closed anti-detect browser |
| --- | --- | --- |
| Engine source | Public (MPL-2.0) | Closed |
| Fingerprint patches | Public, reviewable diffs | Hidden |
| Spoofing layer | C++ inside the engine | Often JavaScript injection |
| Build it yourself | Yes, from this repo | No |
| Profile manager | [AliasMode](https://github.com/aliasmode/aliasmode), open source | Usually closed |

## What it covers

- **Navigator and screen:** user agent, platform, hardware concurrency, touch points, screen and window geometry
- **Graphics:** WebGL vendor, renderer, parameters, and extensions
- **Audio:** AudioContext output and sample rate
- **Fonts:** system font list, CSS system fonts, and font metrics per OS
- **Network:** WebRTC IP, locale, timezone, and geolocation that match the proxy
- **Media:** media devices, codecs, and speech voices
- **Automation:** a hidden Playwright (Juggler) agent, isolated from page scripts, with human-like cursor movement
- **Privacy:** telemetry and data reporting removed at compile time

See [`patches/`](patches) for every change we make to Firefox.

## Use it

**With AliasMode (recommended).** [Download AliasMode](https://aliasmode.com/download/). It installs the engine, creates fingerprint profiles, and manages proxies for you. Free, no account needed.

**Standalone.** Download a build from [Releases](https://github.com/aliasmode/aliasmode-firefox/releases).

## Build from source

The build runs on Linux. Windows and macOS builds are cross-compiled from Linux.

```bash
bash scripts/install-deps.sh
make dir
make bootstrap
make build
make run
```

Full cross-platform build and packaging:

```bash
python3 multibuild.py --target linux windows macos --arch x86_64 arm64
```

To add or change a patch, run `make edits`. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Built on Camoufox

AliasMode Firefox is built on top of [Camoufox](https://github.com/daijro/camoufox) by daijro and its contributors, the leading open-source stealth Firefox. The pinned upstream release is in [`settings/aliasmode-provenance.json`](settings/aliasmode-provenance.json). We thank the Camoufox team for their work.

## License

[MPL-2.0](LICENSE). The AliasMode app is Apache-2.0.
