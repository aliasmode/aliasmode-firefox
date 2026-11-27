"""
Verify a configured position is given only as stock Firefox gives one.

geolocation-spoofing.patch serves geolocation:latitude/longitude as the
position. A page still has to get it as on stock Firefox: on a fresh profile
permissions.query() says "prompt" and getCurrentPosition() waits for the user,
a grant gives the configured position, and a stored denial fails with
PERMISSION_DENIED. With the position configured no location service runs: the
network provider's URL (pointed here at a local server) gets no request. The
control launch without the keys, granted, does reach that server, so a request
would be seen.

    python browser/tests/playwright/patches/geolocation-permission.py
"""

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

CONFIGURED = {"geolocation:latitude": 48.8566, "geolocation:longitude": 2.3522,
              "geolocation:accuracy": 30}
SERVED = {"location": {"lat": -33.8688, "lng": 151.2093}, "accuracy": 1500}

STATE = "async () => (await navigator.permissions.query({name: 'geolocation'})).state"
POSITION = """() => new Promise(resolve => navigator.geolocation.getCurrentPosition(
  p => resolve({lat: p.coords.latitude, lng: p.coords.longitude}),
  e => resolve({error: e.code}), {timeout: 20000}))"""
# A request still waiting on the prompt after this long has not been answered.
UNANSWERED_MS = 3000


class Server(BaseHTTPRequestHandler):
    geo_requests = 0

    def do_GET(self):
        self._reply(b"<!doctype html><title>geo</title>", "text/html")

    def do_POST(self):
        Server.geo_requests += 1
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._reply(json.dumps(SERVED).encode(), "application/json")

    def _reply(self, body, kind):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


async def session(origin, config, prefs, grant):
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, os="linux", config=config,
                             firefox_user_prefs=prefs, i_know_what_im_doing=True,
                             executable_path=str(resolve_binary())) as browser:
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(origin)
        result = {"before": await page.evaluate(STATE)}
        if grant:
            settled = await page.evaluate(
                f"ms => Promise.race([({POSITION})().then(() => true),"
                " new Promise(r => setTimeout(() => r(false), ms))])",
                UNANSWERED_MS)
            result["answered_unasked"] = settled
            await context.grant_permissions(["geolocation"], origin=origin)
            result["after"] = await page.evaluate(STATE)
        result["position"] = await page.evaluate(POSITION)
        return result


async def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    # The Python launcher allows every site by default when the keys are set
    # (permissions.default.geo 1); a stock profile asks.
    prefs = {"permissions.default.geo": 0,
             "geo.provider.network.url": f"{origin}/geo",
             "geo.provider.network.timeToWaitBeforeSending": 0,
             "geo.provider.use_geoclue": False}
    failures = []
    try:
        granted = await session(origin, CONFIGURED, prefs, grant=True)
        print(f"  configured, granted: {granted}")
        if granted["before"] != "prompt":
            failures.append(f"fresh profile reads {granted['before']!r}, stock reads 'prompt'")
        if granted["answered_unasked"]:
            failures.append("the position was given before the user granted it")
        if granted["after"] != "granted":
            failures.append(f"after the grant the state is {granted['after']!r}")
        want = {"lat": CONFIGURED["geolocation:latitude"], "lng": CONFIGURED["geolocation:longitude"]}
        if granted["position"] != want:
            failures.append(f"granted position {granted['position']}, configured {want}")

        denied = await session(origin, CONFIGURED, {**prefs, "permissions.default.geo": 2},
                               grant=False)
        print(f"  configured, denied:  {denied}")
        if denied["before"] != "denied" or denied["position"] != {"error": 1}:
            failures.append(f"a stored denial gave {denied}, stock gives 'denied' and error 1")
        configured_requests = Server.geo_requests
        if configured_requests:
            failures.append(f"{configured_requests} network location request(s) with the position configured")

        control = await session(origin, {}, prefs, grant=True)
        print(f"  not configured:      {control}")
        if Server.geo_requests == configured_requests:
            failures.append("the control launch sent no location request, so none could be seen")
        if control["position"] != {"lat": SERVED["location"]["lat"], "lng": SERVED["location"]["lng"]}:
            failures.append(f"without the keys the position is {control['position']}, not the provider's")
    finally:
        server.shutdown()

    for failure in failures:
        print(f"  FAIL {failure}")
    if failures:
        return 1
    print("  PASS: the configured position follows stock's permission flow, and no location service runs")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
