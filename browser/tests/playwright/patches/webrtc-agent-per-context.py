"""
Verify every peer connection of a context behind a proxy without UDP shows the
same network, whatever servers the page configures.

Behind an HTTP proxy the page sees the ICE agent behind the proxy
(zzz-webrtc-ice-fallback.patch, ci/tribal-rules.yml: no-made-up-srflx). A TURN
server over TCP or TLS is reached through the proxy, so with one the real agent
gathers too, for the relay a call needs. The choice used to follow that page
configuration: a second connection that added such a TURN server got the real
agent alone, and no srflx for the same STUN server the first one got a srflx
from, which no real network gives.

What PASS means: behind an HTTP proxy, a connection with a STUN server and one
with the same STUN server and a TURN server over TCP both show one srflx, the
identity's address, with no error for the STUN server; the second one's TURN
server is asked through the proxy (CONNECT); and this machine's address is in
no candidate or SDP of either.

    python browser/tests/playwright/patches/webrtc-agent-per-context.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import own_address, resolve_binary  # noqa: E402

SPOOFED_IP = "203.0.113.9"
STUN = "stun:198.51.100.1:3478"
TURN_TCP = "turn:198.51.100.2:3478?transport=tcp"
PAGE = b"<!doctype html><title>proxied</title><body>"

GATHER = """async (servers) => {
  const pc = new RTCPeerConnection({iceServers: servers});
  const srflx = [], errors = [], lines = [];
  const ended = new Promise(resolve => {
    setTimeout(() => resolve(false), 30000);
    pc.onicecandidate = e => {
      if (!e.candidate) return resolve(true);
      lines.push(e.candidate.candidate);
      const m = e.candidate.candidate.match(/ (\\S+) \\d+ typ srflx/);
      if (m) srflx.push(m[1]);
    };
    pc.onicecandidateerror = e => errors.push(e.url);
  });
  pc.createDataChannel('probe');
  await pc.setLocalDescription(await pc.createOffer());
  const done = await ended;
  const sdp = pc.localDescription.sdp;
  pc.close();
  return {done, srflx, errors, seen: lines.join('\\n') + '\\n' + sdp};
}"""


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    connects = []

    async def serve_proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readline()
        while (await reader.readline()) not in (b"\r\n", b""):
            pass
        if request.startswith(b"CONNECT "):
            # The TURN server is never reached; the request is what counts.
            connects.append(request.split()[1].decode())
            writer.close()
            return
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n"
                     b"Content-Length: %d\r\n\r\n%s" % (len(PAGE), PAGE))
        await writer.drain()
        writer.close()

    proxy = await asyncio.start_server(serve_proxy, "127.0.0.1", 0)
    port = proxy.sockets[0].getsockname()[1]
    async with AsyncCamoufox(headless=True, os="linux", config={"webrtc:ipv4": SPOOFED_IP},
                             proxy={"server": f"http://127.0.0.1:{port}"}, geoip=False,
                             i_know_what_im_doing=True,
                             executable_path=str(resolve_binary())) as browser:
        page = await browser.new_page()
        await page.goto("http://parity.test/")
        stun_only = await page.evaluate(GATHER, [{"urls": STUN}])
        with_turn = await page.evaluate(
            GATHER, [{"urls": STUN}, {"urls": TURN_TCP, "username": "guard", "credential": "guard"}])
    proxy.close()

    machine = own_address()
    checks = []
    for label, r in (("STUN", stun_only), ("STUN and TURN over TCP", with_turn)):
        checks += [
            (f"{label}: gathering ends", r["done"], r["done"]),
            (f"{label}: the one srflx is the identity's address", r["srflx"] == [SPOOFED_IP], r["srflx"]),
            (f"{label}: no error for the STUN server", STUN not in r["errors"], r["errors"]),
            (f"{label}: this machine's address is in no candidate or SDP", machine not in r["seen"], machine),
        ]
    checks.append(("STUN and TURN over TCP: the TURN server is asked through the proxy",
                   "198.51.100.2:3478" in connects, connects))
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
