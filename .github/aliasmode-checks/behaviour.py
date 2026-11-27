"""AliasMode Firefox vs stock Firefox on the same runner, headed.

For each browser: chrome height (outer - inner height, toolbox), maximize and
restore, focus/blur/visibility events when another window takes focus and
gives it back, and ICE candidates for a public STUN server and for none.
Prints both and the differences; exits 1 when one differs.

    python behaviour.py --ours <exe> --stock <exe> [--out result.json]
"""

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Marionette:
    def __init__(self, port, timeout=90):
        deadline = time.time() + timeout
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.5)
        self.sock.settimeout(timeout)
        self._id = 0
        self._recv()
        self.call("WebDriver:NewSession", {"capabilities": {}})

    def _recv(self):
        buf = b""
        while b":" not in buf:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        size, rest = buf.split(b":", 1)
        while len(rest) < int(size):
            chunk = self.sock.recv(int(size) - len(rest))
            if not chunk:
                raise ConnectionError("closed")
            rest += chunk
        return json.loads(rest)

    def call(self, command, params):
        self._id += 1
        data = json.dumps([0, self._id, command, params]).encode()
        self.sock.sendall(str(len(data)).encode() + b":" + data)
        while True:
            msg = self._recv()
            if isinstance(msg, list) and msg[1] == self._id:
                if msg[2]:
                    raise RuntimeError(f"{command}: {msg[2]}")
                return msg[3]

    def context(self, name):
        self.call("Marionette:SetContext", {"value": name})

    def js(self, script, timeout=30000):
        return self.call("WebDriver:ExecuteAsyncScript",
                         {"script": script, "args": [], "scriptTimeout": timeout}).get("value")


PREFS = {
    "browser.shell.checkDefaultBrowser": False,
    "browser.aboutwelcome.enabled": False,
    "startup.homepage_welcome_url": "",
    "startup.homepage_welcome_url.additional": "",
    "browser.startup.homepage_override.mstone": "ignore",
    "datareporting.policy.dataSubmissionEnabled": False,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "browser.startup.page": 0,
    "browser.tabs.warnOnClose": False,
}

CHROME = """const done = arguments[arguments.length - 1];
const w = Services.wm.getMostRecentWindow("navigator:browser");
done({outer: [w.outerWidth, w.outerHeight], inner: [w.innerWidth, w.innerHeight],
      chrome: w.outerHeight - w.innerHeight,
      toolbox: w.document.getElementById("navigator-toolbox").getBoundingClientRect().height,
      state: w.windowState, screen: [w.screenX, w.screenY],
      avail: [w.screen.availLeft, w.screen.availTop, w.screen.availWidth, w.screen.availHeight],
      dpr: w.devicePixelRatio});"""

MAXIMIZE = """const done = arguments[arguments.length - 1];
const w = Services.wm.getMostRecentWindow("navigator:browser");
const shot = () => ({state: w.windowState, outer: [w.outerWidth, w.outerHeight],
                     screen: [w.screenX, w.screenY]});
const wait = (want) => new Promise(r => {
  const deadline = Date.now() + 5000;
  const tick = () => (w.windowState == want || Date.now() > deadline) ? setTimeout(r, 500) : setTimeout(tick, 50);
  tick();
});
(async () => {
  const before = shot();
  w.maximize(); await wait(w.STATE_MAXIMIZED); const maximized = shot();
  w.restore(); await wait(w.STATE_NORMAL); const restored = shot();
  done({before, maximized, restored});
})();"""

LISTEN = """const done = arguments[arguments.length - 1];
window.__events = [];
for (const t of ["focus", "blur"]) window.addEventListener(t, () => window.__events.push(t));
document.addEventListener("visibilitychange", () => window.__events.push("visibility:" + document.visibilityState));
done({focus: document.hasFocus(), visibility: document.visibilityState});"""

READ = """const done = arguments[arguments.length - 1];
done({events: window.__events, focus: document.hasFocus(), visibility: document.visibilityState});"""

OTHER_WINDOW = """const done = arguments[arguments.length - 1];
const first = Services.wm.getMostRecentWindow("navigator:browser");
const other = first.OpenBrowserWindow();
other.addEventListener("load", () => setTimeout(() => { other.focus(); setTimeout(() => done(true), 1500); }, 500), {once: true});"""

CLOSE_OTHER = """const done = arguments[arguments.length - 1];
const wins = [...Services.wm.getEnumerator("navigator:browser")];
wins[wins.length - 1].close();
setTimeout(() => done(wins.length), 1500);"""

ICE = """const done = arguments[arguments.length - 1];
(async () => {
  const out = {};
  for (const [label, servers] of [["none", []], ["stun", [{urls: "stun:stun.l.google.com:19302"}]]]) {
    const pc = new RTCPeerConnection({iceServers: servers});
    pc.createDataChannel("x");
    const cands = [];
    const start = performance.now();
    const finished = new Promise(r => {
      pc.onicecandidate = e => { if (e.candidate && e.candidate.candidate) cands.push(e.candidate.candidate); else r(); };
      setTimeout(r, 15000);
    });
    await pc.setLocalDescription(await pc.createOffer());
    await finished;
    out[label] = {ms: Math.round(performance.now() - start), candidates: cands.map(c => {
      const f = c.split(" ");
      return {type: f[7], protocol: f[2].toLowerCase(), mdns: f[4].endsWith(".local"), tcptype: f[8] === "tcptype" ? f[9] : null};
    })};
    pc.close();
  }
  done(out);
})();"""


def run_browser(binary):
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="behaviour-") as profile:
        with open(os.path.join(profile, "user.js"), "w") as f:
            f.write(f'user_pref("marionette.port", {port});\n')
            for k, v in PREFS.items():
                f.write(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n")
        env = {**os.environ, "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS": "1"}
        proc = subprocess.Popen([binary, "--marionette", "--no-remote", "--profile", profile, "about:blank"],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = {}
        try:
            m = Marionette(port)
            time.sleep(4)
            m.context("chrome")
            result["version"] = m.js("arguments[0](Services.appinfo.version)")
            result["chrome"] = m.js(CHROME)
            result["maximize"] = m.js(MAXIMIZE)
            m.context("content")
            m.call("WebDriver:Navigate", {"url": "data:text/html,<title>probe</title>probe"})
            result["focus_start"] = m.js(LISTEN)
            m.context("chrome")
            m.js(OTHER_WINDOW)
            m.context("content")
            result["focus_behind"] = m.js(READ)
            m.context("chrome")
            m.js(CLOSE_OTHER)
            m.context("content")
            result["focus_back"] = m.js(READ)
            result["ice"] = m.js(ICE, timeout=60000)
            with contextlib.suppress(Exception):
                m.call("Marionette:Quit", {"flags": ["eForceQuit"]})
        finally:
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
    return result


def compare(ours, stock):
    diffs = []
    if ours["chrome"]["chrome"] != stock["chrome"]["chrome"]:
        diffs.append(f"chrome height {ours['chrome']['chrome']} vs stock {stock['chrome']['chrome']}")
    if ours["chrome"]["toolbox"] != stock["chrome"]["toolbox"]:
        diffs.append(f"toolbox {ours['chrome']['toolbox']} vs stock {stock['chrome']['toolbox']}")
    for step in ("maximized", "restored"):
        if ours["maximize"][step]["state"] != stock["maximize"][step]["state"]:
            diffs.append(f"{step} state {ours['maximize'][step]['state']} vs stock {stock['maximize'][step]['state']}")
    if ours["maximize"]["maximized"]["outer"] != stock["maximize"]["maximized"]["outer"]:
        diffs.append(f"maximized size {ours['maximize']['maximized']['outer']} vs stock {stock['maximize']['maximized']['outer']}")
    for step in ("focus_start", "focus_behind", "focus_back"):
        if ours[step] != stock[step]:
            diffs.append(f"{step} {ours[step]} vs stock {stock[step]}")
    for label in ("none", "stun"):
        kinds = lambda r: sorted((c["type"], c["protocol"], c["mdns"], c["tcptype"]) for c in r["ice"][label]["candidates"])
        if kinds(ours) != kinds(stock):
            diffs.append(f"ICE {label}: {kinds(ours)} vs stock {kinds(stock)}")
    return diffs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ours", required=True)
    parser.add_argument("--stock", required=True)
    parser.add_argument("--upstream", help="Camoufox of the same release, for reference only")
    parser.add_argument("--out")
    args = parser.parse_args()
    stock = run_browser(args.stock)
    ours = run_browser(args.ours)
    print("stock:", json.dumps(stock, indent=1))
    print("ours: ", json.dumps(ours, indent=1))
    diffs = compare(ours, stock)
    result = {"stock": stock, "ours": ours, "diffs": diffs}
    if args.upstream:
        upstream = run_browser(args.upstream)
        result["upstream"] = upstream
        result["upstream_diffs"] = compare(upstream, stock)
        for d in result["upstream_diffs"]:
            print("UPSTREAM CAMOUFOX DIFF", d)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(result, f, indent=1)
    for d in diffs:
        print("DIFF", d)
    print("SAME as stock" if not diffs else f"{len(diffs)} difference(s)")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
