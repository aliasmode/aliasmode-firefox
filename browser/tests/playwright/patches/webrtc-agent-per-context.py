"""
Verify every peer connection of a context behind a proxy without UDP shows the
same network, whatever servers and media the page configures, under the prefs
the AliasMode app sets behind a proxy.

Behind an HTTP proxy the page sees the ICE agent behind the proxy
(zzz-webrtc-ice-fallback.patch, ci/tribal-rules.yml: no-made-up-srflx). A TURN
server over TCP or TLS is reached through the proxy, so with one the real agent
gathers too, for the relay a call needs. The choice used to follow that page
configuration: a second connection that added such a TURN server got the real
agent alone, and no srflx for the same STUN server the first one got a srflx
from, which no real network gives. Under the app's prefs (no_host hides the
real agent's host candidates) that connection then got its srflx on a port no
host candidate had, and its host candidates after end-of-candidates. And the
ICE agent behind the proxy gathered for the first transport and component only,
where nICEr gathers every transport of the offer (audio and video apart under
the balanced and max-compat bundle policies) and both components of an RTP
one.

What PASS means: behind an HTTP proxy, with the app's prefs, a data channel
connection with a STUN server and one with the same STUN server and a TURN
server over TCP show the same candidates: per component a host UDP and a host
TCP candidate and one srflx on the host UDP port, with the identity's address,
and no error for the STUN server. An audio and video offer shows them for every
m-section that is not bundle-only, for both components. No candidate comes
after its m-section's end-of-candidates or after the final one, the TURN server
is asked through the proxy (CONNECT), and this machine's address is in no
candidate or SDP.

    python browser/tests/playwright/patches/webrtc-agent-per-context.py
"""

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import own_address, resolve_binary  # noqa: E402

SPOOFED_IP = "203.0.113.9"
STUN = "stun:198.51.100.1:3478"
TURN_TCP = "turn:198.51.100.2:3478?transport=tcp"
PAGE = b"<!doctype html><title>proxied</title><body>"
# What the AliasMode app sets behind a proxy (firefox-worker.mjs).
APP_PREFS = {
    "media.peerconnection.ice.proxy_only": True,
    "media.peerconnection.ice.default_address_only": True,
    "media.peerconnection.ice.no_host": True,
}

GATHER = """async ([servers, media, bundlePolicy]) => {
  const pc = new RTCPeerConnection({iceServers: servers, bundlePolicy});
  const events = [], errors = [];
  const ended = new Promise(resolve => {
    setTimeout(() => resolve(false), 30000);
    pc.onicecandidate = e => {
      events.push(e.candidate ? [e.candidate.sdpMid, e.candidate.candidate] : null);
      if (!e.candidate) resolve(true);
    };
    pc.onicecandidateerror = e => errors.push(e.url);
  });
  for (const kind of media) {
    if (kind === 'data') pc.createDataChannel('probe'); else pc.addTransceiver(kind);
  }
  await pc.setLocalDescription(await pc.createOffer());
  const done = await ended;
  // Anything late would arrive in this time.
  await new Promise(resolve => setTimeout(resolve, 500));
  const sdp = pc.localDescription.sdp;
  pc.close();
  return {done, events, errors, sdp};
}"""


def gathering_sections(sdp):
    """mid -> components, for the m-sections of an offer that gather."""
    sections = {}
    for block in sdp.split("\r\nm=")[1:]:
        lines = block.split("\r\n")
        mid = next(line[len("a=mid:"):] for line in lines if line.startswith("a=mid:"))
        if lines[0].split()[1] != "0":
            sections[mid] = 2 if "RTP" in lines[0].split()[2] else 1
    return sections


def check(label, r, machine):
    failures = []
    if not r["done"]:
        failures.append("gathering never ends")
    shape, srflx_ports, host_ports, ended = set(), {}, {}, set()
    for i, event in enumerate(r["events"]):
        if event is None:
            if i != len(r["events"]) - 1:
                failures.append(f"events after the final end-of-candidates: {r['events'][i + 1:]}")
            break
        mid, line = event
        if not line:
            ended.add(mid)
            continue
        if mid in ended:
            failures.append(f"m-section {mid}: {line} after its end-of-candidates")
        f = line.split()
        component, protocol, address, port, kind = f[1], f[2].lower(), f[4], f[5], f[7]
        if kind == "relay":
            continue
        shape.add((mid, component, kind, protocol))
        if kind == "srflx":
            if address != SPOOFED_IP:
                failures.append(f"srflx {line} is not at the identity's address")
            srflx_ports[(mid, component)] = port
        elif protocol == "udp":
            host_ports[(mid, component)] = port
    want = {(mid, str(c), kind, protocol)
            for mid, components in gathering_sections(r["sdp"]).items()
            for c in range(1, components + 1)
            for kind, protocol in (("host", "udp"), ("host", "tcp"), ("srflx", "udp"))}
    if shape != want:
        failures.append(f"candidates {sorted(shape)}, not nICEr's {sorted(want)}")
    if srflx_ports != host_ports:
        failures.append(f"srflx ports {srflx_ports} are not the host UDP ports {host_ports}")
    if STUN in r["errors"]:
        failures.append(f"an error for the STUN server: {r['errors']}")
    seen = "\n".join(e[1] for e in r["events"] if e) + "\n" + r["sdp"]
    if machine in seen:
        failures.append(f"this machine's address {machine} is in a candidate or the SDP")
    print(f"  {label}: {[e for e in r['events']]}")
    return [f"{label}: {f}" for f in failures]


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

    stun = [{"urls": STUN}]
    turn = [{"urls": STUN}, {"urls": TURN_TCP, "username": "guard", "credential": "guard"}]
    cases = [
        ("data, STUN", stun, ["data"], "balanced"),
        ("data, STUN and TURN over TCP", turn, ["data"], "balanced"),
        ("audio and video, balanced", stun, ["audio", "video"], "balanced"),
        ("audio and video, max-compat", stun, ["audio", "video"], "max-compat"),
        ("audio and video, STUN and TURN over TCP", turn, ["audio", "video"], "balanced"),
    ]
    proxy = await asyncio.start_server(serve_proxy, "127.0.0.1", 0)
    port = proxy.sockets[0].getsockname()[1]
    results = {}
    async with AsyncCamoufox(headless=True, os="linux", config={"webrtc:ipv4": SPOOFED_IP},
                             proxy={"server": f"http://127.0.0.1:{port}"}, geoip=False,
                             firefox_user_prefs=APP_PREFS, i_know_what_im_doing=True,
                             executable_path=str(resolve_binary())) as browser:
        page = await browser.new_page()
        await page.goto("http://parity.test/")
        for label, servers, media, policy in cases:
            results[label] = await page.evaluate(GATHER, [servers, media, policy])
    proxy.close()

    machine = own_address()
    failures = []
    for label, r in results.items():
        failures += check(label, r, machine)
    shapes = {label: sorted({tuple(re.split(r"\s+", e[1])[i] for i in (1, 2, 7))
                             for e in r["events"] if e and e[1] and " typ relay" not in e[1]})
              for label, r in results.items() if label.startswith("data")}
    if len(set(map(tuple, shapes.values()))) != 1:
        failures.append(f"the data channel connections show different candidates: {shapes}")
    if "198.51.100.2:3478" not in connects:
        failures.append(f"the TURN server was not asked through the proxy: {connects}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: every connection of the context shows the same network, for every transport and component")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
