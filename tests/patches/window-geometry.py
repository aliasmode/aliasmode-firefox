r"""
Verify window geometry a page reads is the real window, placed on the screen
the identity claims (window-screen-position.patch, CamoufoxWindow.sys.mjs).

The identity claims a screen whose available area starts at x=1920 (a second
monitor) and asks for a first window larger than that area. Read from the
page's own world, a page must see:

  first     outerWidth/outerHeight no larger than screen.availWidth/availHeight,
            and never smaller than innerWidth/innerHeight
  position  screenX/screenY inside the claimed available area, and
            mozInnerScreenX/Y no further from them than the window frame
  pointer   a real click's screenX - clientX equal to mozInnerScreenX; an event
            the page builds keeps the screenX it was given
  resize    a resize past the claimed area is undone
  label     the aliasmode:windowLabel config leads the browser window's title,
            while the page's document.title is untouched

    python tests/patches/window-geometry.py
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, marionette_args, resolve_binary  # noqa: E402

CONFIG = {
    "screen.width": 1200, "screen.height": 740,
    "screen.availLeft": 1920, "screen.availTop": 0, "screen.availWidth": 1200, "screen.availHeight": 700,
    "window.outerWidth": 1500, "window.outerHeight": 1000,
    "aliasmode:windowLabel": "Profile 7",
}
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

CHROME_TITLE = 'return Services.wm.getMostRecentWindow("navigator:browser").document.title;'
CHROME_RESIZE = 'Services.wm.getMostRecentWindow("navigator:browser").resizeTo(2400, 1600); return true;'


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


def main() -> int:
    from camoufox.sync_api import Camoufox

    binary = resolve_binary()
    failures = []
    profile = tempfile.mkdtemp(prefix="window-geometry-")
    # Marionette writes the port it really listens on into the profile.
    with Camoufox(headless=True, executable_path=str(binary), args=marionette_args(),
                  persistent_context=True, user_data_dir=profile, config=CONFIG,
                  main_world_eval=True, i_know_what_im_doing=True) as context:
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

        port_file = Path(profile) / "MarionetteActivePort"
        deadline = time.time() + 30
        while not port_file.exists() and time.time() < deadline:
            time.sleep(0.5)
        m = Marionette(int(port_file.read_text()))
        try:
            chrome_title = m.js(CHROME_TITLE)
            m.js(CHROME_RESIZE)
        finally:
            m.close()
        time.sleep(2)
        resized = page.evaluate(GEOMETRY)
        print(f"resize: {resized}")
        check_geometry(resized, "resize", failures)

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
    print("PASS: pages read the real window, placed on the claimed screen, and only the window title carries the label.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
