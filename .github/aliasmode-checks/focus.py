"""Throwaway: where the first window's focus comes back from on macOS, per browser and pref."""
import contextlib, json, os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(__file__))
from behaviour import Marionette, PREFS, LISTEN, READ, free_port

STATE = """const done = arguments[arguments.length - 1];
const wins = [...Services.wm.getEnumerator("navigator:browser")];
const fm = Services.focus;
done({count: wins.length, active: wins.indexOf(fm.activeWindow), focused: fm.focusedWindow ? String(fm.focusedWindow.location).slice(0, 40) : null,
      hasFocus: wins.map(w => w.document.hasFocus())});"""
OTHER = """const done = arguments[arguments.length - 1];
const first = Services.wm.getMostRecentWindow("navigator:browser");
const other = first.OpenBrowserWindow();
other.addEventListener("load", () => setTimeout(() => { %s setTimeout(() => done(true), 1500); }, 500), {once: true});"""
CLOSE = """const done = arguments[arguments.length - 1];
const wins = [...Services.wm.getEnumerator("navigator:browser")];
wins[wins.length - 1].close();
setTimeout(() => done(wins.length), 1500);"""
TRACE = """const done = arguments[arguments.length - 1];
const first = [...Services.wm.getEnumerator("navigator:browser")][0];
window.__trace = [];
for (const t of ["focus", "blur", "activate", "deactivate"]) first.addEventListener(t, e => { if (e.target === first || e.target === first.document) window.__trace.push(t + "@" + Math.round(performance.now())); }, true);
done(true);"""
READTRACE = "arguments[arguments.length - 1](window.__trace)"

def run(binary, prefs, other_focus):
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="focus-") as profile:
        with open(os.path.join(profile, "user.js"), "w") as f:
            f.write(f'user_pref("marionette.port", {port});\n')
            for k, v in {**PREFS, **prefs}.items():
                f.write(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n")
        env = {**os.environ, "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS": "1"}
        proc = subprocess.Popen([binary, "--marionette", "--no-remote", "--profile", profile, "about:blank"], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out = {}
        try:
            m = Marionette(port); time.sleep(4)
            m.context("content"); m.call("WebDriver:Navigate", {"url": "data:text/html,<title>probe</title>probe"})
            out["start"] = m.js(LISTEN)
            m.context("chrome"); m.js(TRACE); out["state0"] = m.js(STATE)
            m.js(OTHER % other_focus); out["state1"] = m.js(STATE)
            m.context("content"); out["behind"] = m.js(READ)
            m.context("chrome"); m.js(CLOSE); out["state2"] = m.js(STATE); out["trace"] = m.js(READTRACE)
            m.context("content"); out["back"] = m.js(READ)
            with contextlib.suppress(Exception):
                m.call("Marionette:Quit", {"flags": ["eForceQuit"]})
        finally:
            try: proc.wait(timeout=20)
            except subprocess.TimeoutExpired: proc.kill()
    return out

if __name__ == "__main__":
    ours, stock, up = sys.argv[1:4]
    res = {}
    for name, b, prefs, of in [
        ("stock", stock, {}, "other.focus();"),
        ("upstream", up, {}, "other.focus();"),
        ("ours", ours, {}, "other.focus();"),
        ("ours+emulate", ours, {"aliasmode.focus.emulate_active_window": True}, "other.focus();"),
        ("stock-nofocuscall", stock, {}, ""),
        ("ours-nofocuscall", ours, {}, ""),
    ]:
        try:
            res[name] = run(b, prefs, of)
        except Exception as e:
            res[name] = {"error": repr(e)}
        print(name, json.dumps(res[name]), flush=True)
    json.dump(res, open("focus.json", "w"), indent=1)
