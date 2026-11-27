r"""
Verify a profile's canvas encodes the same way on every launch.

Stock Firefox (EfficientCanvasRandomization, on in normal windows) writes a
deBG chunk into every PNG toDataURL/toBlob encodes: a hash of the pixels keyed
by a browsing session key, a fresh UUID per launch. The pixels of an AliasMode
profile are stable (aliasmode:canvasSeed), yet its toDataURL hash changed on
every open. With a seed the key now comes from the seed, so:

  - the same seed encodes the same canvas to the same bytes on two launches;
  - another seed encodes it to other bytes (no cross-profile link);
  - the deBG chunk is still there, as in stock Firefox.

    python tests/patches/canvas-encode-key-stable.py
"""

import base64
import http.server
import os
import struct
import sys
import threading

DRAW = """() => {
  const c = document.createElement('canvas'); c.width = 240; c.height = 60;
  const x = c.getContext('2d');
  x.font = '14px Arial'; x.fillStyle = '#069'; x.fillText('Cwm fjordbank glyphs vext quiz', 2, 30);
  x.beginPath(); x.arc(200, 30, 15, 0, Math.PI * 2); x.strokeStyle = '#a0f'; x.stroke();
  return c.toDataURL();
}"""


def chunks(data_url: str) -> dict:
    png = base64.b64decode(data_url.split(",", 1)[1])
    found, i = {}, 8
    while i < len(png):
        (n,) = struct.unpack(">I", png[i:i + 4])
        found.setdefault(png[i + 4:i + 8].decode("latin-1"), []).append(png[i + 8:i + 8 + n])
        i += 12 + n
    return found


def encode(port: int, seed: int) -> str:
    from camoufox.sync_api import Camoufox
    kwargs = dict(headless=True, config={"aliasmode:canvasSeed": seed}, i_know_what_im_doing=True)
    if os.environ.get("CAMOUFOX_EXECUTABLE_PATH"):
        kwargs["executable_path"] = os.environ["CAMOUFOX_EXECUTABLE_PATH"]
    with Camoufox(**kwargs) as browser:
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{port}/")
        return page.evaluate(DRAW)


def main() -> int:
    class Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<!doctype html><title>canvas</title>")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        first, second, other = encode(port, 1234567), encode(port, 1234567), encode(port, 7654321)
    finally:
        server.shutdown()
    debg = [chunks(url).get("deBG") for url in (first, second, other)]
    print(f"  seed 1234567, launch 1: deBG {debg[0]}")
    print(f"  seed 1234567, launch 2: deBG {debg[1]}")
    print(f"  seed 7654321          : deBG {debg[2]}")
    failures = []
    if not all(debg):
        failures.append("no deBG chunk: EfficientCanvasRandomization is off, unlike stock Firefox")
    if first != second:
        failures.append("the same seed encoded the same canvas differently on two launches")
    if first == other:
        failures.append("two seeds encoded the canvas to the same bytes: profiles are linkable")
    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: one seed encodes a canvas the same on every launch, another seed differently.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
