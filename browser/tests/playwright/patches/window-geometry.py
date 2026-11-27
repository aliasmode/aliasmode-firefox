r"""
Verify window geometry a page reads is the real window, inside the screen the
identity claims (CamoufoxWindow.sys.mjs), with the config the AliasMode app
sends: a Windows identity (fitDesktopPersona) whose available area is the
screen less the 48 px taskbar, at 0,0, as Firefox's baseline protection reports
it, a first window larger than that area, and no window position: the app
drops window.screenX/Y (firefox-config.ts DROPPED_LAUNCH_KEYS). Read from the
page's own world, a page must see:

  first     outerWidth/outerHeight no larger than screen.availWidth/availHeight,
            and never smaller than innerWidth/innerHeight
  position  screenX/screenY inside the claimed available area, and
            mozInnerScreenX/Y no further from them than the window frame
  pointer   a real click's screenX - clientX equal to mozInnerScreenX; an event
            the page builds keeps the screenX it was given
  resize    a resize past the claimed area is undone
  maximize  on a real screen larger than the claimed one, a maximize gives the
            window the claimed available area at availLeft/availTop, and a
            second maximize brings back the window from before; on a real
            screen no larger than the claimed one, a maximize stays maximized,
            also right after startup
  label     the aliasmode:windowLabel config leads the browser window's title,
            while the page's document.title is untouched
  elsewhere on a real desktop whose available area does not start at 0,0 (a
            dock on the left and a panel on top, as on Ubuntu, or a second
            monitor), with an identity whose available area starts at
            x=1920, the window's real position, as stock Firefox reports it:
            the page reads baseline protection's 0,0 area, and screenX/Y,
            mozInnerScreenX/Y and a click's screenX where the window is. They
            used to be moved by the offset between the two areas
            (window-screen-position.patch, removed), so a window at the
            desktop's corner read -70,-32.

The headless screen is the real one: MOZ_HEADLESS_WIDTH x MOZ_HEADLESS_HEIGHT,
1366x768 unless set. The last case runs on a private Xvfb display whose
_NET_WORKAREA plays the desktop.

    python tests/patches/window-geometry.py
"""

import contextlib
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from helpers import Marionette, hidden_display, marionette_args, marionette_env, resolve_binary  # noqa: E402

CONFIG = {
    "navigator.platform": "Win32",
    "screen.width": 1200, "screen.height": 740,
    "screen.availLeft": 0, "screen.availTop": 0, "screen.availWidth": 1200, "screen.availHeight": 692,
    "window.outerWidth": 1500, "window.outerHeight": 1000,
    "aliasmode:windowLabel": "Profile 7",
    "allowMainWorld": True,
}
# An identity drawn on a second monitor, and a desktop with a 70 px dock on the
# left and a 32 px panel on top.
ELSEWHERE = {**CONFIG, "screen.width": 1280, "screen.height": 800, "screen.availLeft": 1920,
             "screen.availWidth": 1280, "screen.availHeight": 752,
             "window.outerWidth": 900, "window.outerHeight": 600}
WORKAREA = (70, 32, 1330, 868)
SMALL_SCREEN = {"MOZ_HEADLESS_WIDTH": "1100", "MOZ_HEADLESS_HEIGHT": "650"}
PAGE = "data:text/html,<title>probe</title><body style='margin:0'>probe</body>"

GEOMETRY = """mw:({
  outer: [outerWidth, outerHeight], inner: [innerWidth, innerHeight],
  screen: [screenX, screenY], mozInner: [mozInnerScreenX, mozInnerScreenY],
  avail: [screen.availLeft, screen.availTop, screen.availWidth, screen.availHeight],
  title: document.title,
})"""

LISTEN = """mw:addEventListener('click', e => {
  window.__click = {screen: [e.screenX, e.screenY], client: [e.clientX, e.clientY],
                    mozInner: [mozInnerScreenX, mozInnerScreenY]};
}, {once: true})"""

BUILT = "mw:new MouseEvent('click', {screenX: 7, screenY: 9}).screenX"

CHROME_WINDOW = 'const w = Services.wm.getMostRecentWindow("navigator:browser");'
CHROME_TITLE = CHROME_WINDOW + " return w.document.title;"
CHROME_RESIZE = CHROME_WINDOW + " w.resizeTo(2400, 1600); return true;"
CHROME_PLACE = CHROME_WINDOW + " w.moveTo(40, 30); w.resizeTo(900, 600); return true;"
CHROME_MAXIMIZE = CHROME_WINDOW + " w.maximize(); return true;"
CHROME_STATE = CHROME_WINDOW + " return w.windowState;"
STATE_MAXIMIZED = 1


def check_geometry(g, where, failures):
    (ow, oh), (iw, ih) = g["outer"], g["inner"]
    left, top, width, height = g["avail"]
    if ow > width or oh > height:
        failures.append(f"{where}: outer {ow}x{oh} is larger than the claimed available area {width}x{height}")
    if ow < iw or oh < ih:
        failures.append(f"{where}: outer {ow}x{oh} is smaller than inner {iw}x{ih}")
    (x, y), (mx, my) = g["screen"], g["mozInner"]
    if x < left or y < top or x + ow > left + width or y + oh > top + height:
        failures.append(f"{where}: window at {x},{y} {ow}x{oh} is outside the claimed area {g['avail']}")
    if not (0 <= mx - x <= ow - iw and 0 <= my - y <= oh - ih):
        failures.append(f"{where}: mozInnerScreen {mx},{my} is not inside the window frame at {x},{y}")


@contextlib.contextmanager
def launch(binary, profile, env=None, config=CONFIG, headless=True):
    """A persistent context, launched as the app launches the engine: the
    config in CAMOU_CONFIG, through Playwright, with no viewport."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # Marionette writes the port it really listens on into the profile.
        context = p.firefox.launch_persistent_context(
            profile, executable_path=str(binary), headless=headless, args=marionette_args(),
            env={**marionette_env(), "CAMOU_CONFIG_1": json.dumps(config), **(env or {})},
            no_viewport=True)
        try:
            yield context
        finally:
            context.close()


def marionette(profile) -> Marionette:
    port_file = Path(profile) / "MarionetteActivePort"
    deadline = time.time() + 30
    while not port_file.exists() and time.time() < deadline:
        time.sleep(0.5)
    return Marionette(int(port_file.read_text()))


def elsewhere(binary, failures):
    """The window's real position on a desktop whose available area does not
    start at 0,0, for an identity drawn on a second monitor."""
    spec = importlib.util.spec_from_file_location("frame_extents", HERE / "startup-size-frame-extents.py")
    x = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(x)
    with hidden_display(screen="1400x900"):
        # The EWMH workarea a desktop's window manager announces; GDK reads it
        # as the screen's available area.
        x11 = x.X11()
        x11.set32(x11.root, "_NET_SUPPORTING_WM_CHECK", x.XA_WINDOW, [x11.root])
        x11.set32(x11.root, "_NET_SUPPORTED", x.XA_ATOM,
                  [x11.atom("_NET_WORKAREA"), x11.atom("_NET_CURRENT_DESKTOP")])
        x11.set32(x11.root, "_NET_CURRENT_DESKTOP", x.XA_CARDINAL, [0])
        x11.set32(x11.root, "_NET_WORKAREA", x.XA_CARDINAL, list(WORKAREA))
        profile = tempfile.mkdtemp(prefix="window-geometry-elsewhere-")
        with launch(binary, profile, config=ELSEWHERE, headless=False) as context:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(PAGE)
            m = marionette(profile)
            try:
                corner = page.evaluate(GEOMETRY)
                real_corner = m.js(CHROME_WINDOW + " return [w.screenX, w.screenY];")
                m.js(CHROME_WINDOW + " w.moveTo(300, 100); return true;")
                deadline = time.time() + 10
                while m.js(CHROME_WINDOW + " return [w.screenX, w.screenY];") != [300, 100]:
                    if time.time() > deadline:
                        failures.append("elsewhere: the window never reached 300,100")
                        return
                    time.sleep(0.2)
                moved = page.evaluate(GEOMETRY)
                page.evaluate(LISTEN)
                page.mouse.click(100, 100)
                time.sleep(0.5)
                click = page.evaluate("mw:window.__click")
            finally:
                m.close()
    print(f"elsewhere: at {real_corner} the page read {corner}; at [300, 100] {moved}, click {click}")
    for where, g, real in (("elsewhere, first", corner, real_corner), ("elsewhere, moved", moved, [300, 100])):
        if g["avail"] != [0, 0, 1280, 752]:
            failures.append(f"{where}: the page reads the available area {g['avail']}, "
                            "not baseline protection's 1280x752 at 0,0")
        if g["screen"] != real:
            failures.append(f"{where}: the page reads the window at {g['screen']}, not where it is, {real}")
        if not (0 <= g["mozInner"][0] - g["screen"][0] <= g["outer"][0] - g["inner"][0]
                and 0 <= g["mozInner"][1] - g["screen"][1] <= g["outer"][1] - g["inner"][1]):
            failures.append(f"{where}: mozInnerScreen {g['mozInner']} is not inside the window frame at {g['screen']}")
    if not click:
        failures.append("elsewhere: the click never reached the page")
    elif any(abs(click["screen"][i] - click["client"][i] - round(click["mozInner"][i])) > 1 for i in (0, 1)):
        failures.append(f"elsewhere: click screen {click['screen']} - client {click['client']} "
                        f"!= mozInnerScreen {click['mozInner']}")


def main() -> int:
    binary = resolve_binary()
    failures = []
    profile = tempfile.mkdtemp(prefix="window-geometry-")
    with launch(binary, profile) as context:
        # The window loaded before the launch returned; the startup hold ends five seconds after that.
        hold_ends = time.time() + 5.5
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(PAGE)
        time.sleep(1)
        first = page.evaluate(GEOMETRY)
        print(f"first:  {first}")
        check_geometry(first, "first", failures)

        page.evaluate(LISTEN)
        page.mouse.click(100, 100)
        time.sleep(0.5)
        click = page.evaluate("mw:window.__click")
        built = page.evaluate(BUILT)
        print(f"click:  {click}, page-built event screenX {built}")
        if not click:
            failures.append("pointer: the click never reached the page")
        elif any(abs(click["screen"][i] - click["client"][i] - round(click["mozInner"][i])) > 1 for i in (0, 1)):
            failures.append(f"pointer: screen {click['screen']} - client {click['client']} != mozInnerScreen {click['mozInner']}")
        if built != 7:
            failures.append(f"pointer: a page-built MouseEvent reads screenX {built}, not the 7 it was given")

        m = marionette(profile)
        try:
            chrome_title = m.js(CHROME_TITLE)
            m.js(CHROME_RESIZE)
            time.sleep(2)
            resized = page.evaluate(GEOMETRY)
            print(f"resize: {resized}")
            check_geometry(resized, "resize", failures)

            # The real 1366x768 screen is larger than the claimed 1200x692 area.
            time.sleep(max(0.0, hold_ends - time.time()))
            m.js(CHROME_PLACE)
            time.sleep(1)
            placed = page.evaluate(GEOMETRY)
            m.js(CHROME_MAXIMIZE)
            time.sleep(1.5)
            maximized = page.evaluate(GEOMETRY)
            m.js(CHROME_MAXIMIZE)
            time.sleep(1.5)
            again = page.evaluate(GEOMETRY)
        finally:
            m.close()
        print(f"maximize: before {placed['outer']} at {placed['screen']}, maximized {maximized['outer']} at "
              f"{maximized['screen']}, maximized again {again['outer']} at {again['screen']}")
        check_geometry(maximized, "maximize", failures)
        if maximized["outer"] != [1200, 692] or maximized["screen"] != [0, 0]:
            failures.append(f"maximize: on a larger real screen a maximize gave {maximized['outer']} at {maximized['screen']}, "
                            "not the claimed available area 1200x692 at 0,0")
        if (again["outer"], again["screen"]) != (placed["outer"], placed["screen"]):
            failures.append(f"maximize: a second maximize gave {again['outer']} at {again['screen']}, "
                            f"not the window from before, {placed['outer']} at {placed['screen']}")

    # A real 1100x650 screen is smaller than the claimed area. Maximize at once, inside the startup hold.
    small = tempfile.mkdtemp(prefix="window-geometry-small-")
    with launch(binary, small, SMALL_SCREEN) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(PAGE)
        m = marionette(small)
        try:
            m.js(CHROME_MAXIMIZE)
            time.sleep(1.5)
            state = m.js(CHROME_STATE)
        finally:
            m.close()
        held = page.evaluate(GEOMETRY)
    print(f"maximize on a smaller screen: state {state}, {held}")
    check_geometry(held, "maximize on a smaller screen", failures)
    if state != STATE_MAXIMIZED or held["outer"] != [1100, 650]:
        failures.append(f"maximize: on a real screen smaller than the claimed one the window is in state {state} "
                        f"at {held['outer']}, not maximized at 1100x650")

    elsewhere(binary, failures)

    print(f"label:  window title {chrome_title!r}, page title {first['title']!r}")
    if not chrome_title.startswith("Profile 7 — "):
        failures.append(f"label: the window title {chrome_title!r} does not start with the label")
    if first["title"] != "probe":
        failures.append(f"label: the page's document.title is {first['title']!r}, not 'probe'")

    print()
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: pages read the real window, inside the claimed screen and where it really is, a maximize "
          "keeps to that screen, and only the window title carries the label.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
