# Patch Dependencies

Quick reference for the shared infrastructure patches build on. `scripts/patch.py`
applies every `patches/**/*.patch` in order of file name, so the
`playwright/0-*` and `playwright/1-*` patches go first and the rest follow
alphabetically. The dependencies below are compile-time: a patch applies without
them, but the tree will not build.

## camoucfg (MaskConfig)

`additions/camoucfg/MaskConfig.hpp` reads the spoofing config (`CAMOU_CONFIG` /
`camoufox.cfg`) through `MaskConfig::GetBool()`, `GetString()`, `GetUint32()`
and friends. `scripts/copy-additions.sh` copies it into the source tree before
any patch applies. A patch that calls MaskConfig from a directory whose
`moz.build` does not already see `/camoucfg` must add
`LOCAL_INCLUDES += ["/camoucfg"]` itself.

Config keys are declared in `settings/properties.json`; a key a patch reads must
be listed there.

### Patches that read config

| Patch | Config keys |
|-------|-------------|
| `audio-context-spoofing.patch` | `AudioContext:outputLatency` |
| `audio-fingerprint-manager.patch` | `audio:seed` |
| `audio-noise-on-copy.patch` | `audio:seed` (noises a copy of the AnalyserNode frequency data; needs `audio-fingerprint-manager.patch`) |
| `canvas-readback-noise.patch` | `aliasmode:canvasSeed` (adds `dom/canvas/AliasModeReadbackNoise.h`) |
| `chromeutil.patch` | `debug` |
| `fingerprint-injection.patch` | `navigator.*`, `screen.*`, `window.*` |
| `font-hijacker.patch` | `navigator.platform` |
| `font-pack-dir.patch` | `aliasmode:fontsDir` (a font pack directory activated with the bundled `fonts/`; needs `font-hijacker.patch`) |
| `font-system-fonts-css2.patch` | `navigator.platform`, `window.devicePixelRatio` |
| `force-default-pointer.patch` | `navigator.maxTouchPoints` |
| `geolocation-spoofing.patch` | `geolocation:*` |
| `global-style-sheets.patch` | `disableTheming` |
| `glyph-advance-noise.patch` | `aliasmode:textSeed` (per font, keyed by the font's PostScript name, so neither its folder nor a web font load changes it) |
| `locale-spoofing.patch` | `locale:*`, `navigator.language` |
| `media-codec-spoofing.patch` | `media:spoof_codecs` (bypasses `PDMFactory::Supports()` in `MP4Decoder`/`MatroskaDecoder` so `canPlayType()`/`isTypeSupported()` don't leak system codec libraries) |
| `media-device-spoofing.patch` | `mediaDevices:*` |
| `navigator-spoofing.patch` | `navigator.*`, `timezone` |
| `network-ipv4-only.patch` | `network:ipv4Only` (no IPv6 route: IPv4-only lookups, IPv6 connects and ICE candidates fail as on such a host) |
| `network-patches.patch` | `headers.*`, `navigator.userAgent` |
| `no-css-animations.patch` | `instantAnimations` |
| `screen-spoofing.patch` | `screen.width`, `screen.height` |
| `screen-workarea-baseline.patch` | `navigator.platform` (read through `Navigator::GetPlatform`; the available area follows stock baseline protection; needs `screen-spoofing.patch`) |
| `system-ui-font-spoofing.patch` | `navigator.platform` |
| `timezone-spoofing.patch` | `timezone` |
| `touchscreen-fingerprint-spoofing.patch` | `navigator.maxTouchPoints` |
| `touchscreen-points-baseline.patch` | `navigator.maxTouchPoints` (collapsed as stock baseline protection does; needs `touchscreen-fingerprint-spoofing.patch`) |
| `voice-spoofing.patch` | `voices:*` |
| `webgl-spoofing.patch` | `webGl:*` |
| `webgl-stated-limits.patch` | `webGl:parameters`, `webGl2:parameters` (read where the WebGL context runs, so a stated limit binds) |
| `webgl-unmasked-renderer-and-readback.patch` | `webGl:renderer`, `aliasmode:canvasSeed` (applies after `webgl-spoofing.patch`; needs `canvas-readback-noise.patch`) |
| `webrtc-ip-spoofing.patch` | `webrtc:ipv4`, `webrtc:ipv6`, `navigator.platform` |
| `webrtc-port-range.patch` | `navigator.platform` (host UDP sockets get ports as the identity OS hands them out: its range, in sequence on Windows) |
| `webrtc-proxy-ice-agent.patch` | `webrtc:ipv4`, `webrtc:ipv6`, `navigator.platform` (the ICE agent a page sees behind the enforced proxy; applies after `webrtc-ip-spoofing.patch`) |

To regenerate the list: `grep -l 'MaskConfig::' patches/*.patch`.

## RoverfoxStorageManager

Per-context values set from Playwright (audio seed, WebRTC IP, timezone,
screen, navigator, voices, ...) are kept in `RoverfoxStorageManager`, which
`anti-font-fingerprinting.patch` adds under `dom/base/`. Its cross-process
put/get IPC lives in `cross-process-storage.patch`. Any patch that uses the
storage manager needs both.

## Playwright

Everything else is written against a tree that already has
`playwright/0-playwright.patch` and `playwright/1-leak-fixes.patch` applied.
