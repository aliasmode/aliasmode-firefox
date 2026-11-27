"""A toolbar state AliasMode Firefox 156 saved takes Firefox 159's own step 27.

AliasMode 156 saved CustomizableUI version 27 for its own repair step, where
stock Firefox 156 saves 26 (tab-layout-repair.patch). Firefox 159's step 27
moves an Organize Tabs button that was appended after the Smart Window
switcher back in front of it. The state below is the one AliasMode 156 saved
for a profile whose state predates that button. Measured: stock 156 -> stock
159 ends with the button before the switcher, and so must this build. The same
layout saved at version 28 (Firefox 159 already ran step 27) is the user's own
order and stays.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from helpers import Marionette, free_port, marionette_args, marionette_env, resolve_binary


TABSTRIP = ["tabbrowser-tabs", "new-tab-button", "customizableui-special-spring3",
            "alltabs-button", "ai-window-toggle", "smartwindow-group-tabs-button"]
STOCK_159 = ["tabbrowser-tabs", "new-tab-button", "customizableui-special-spring3",
             "alltabs-button", "smartwindow-group-tabs-button", "ai-window-toggle"]

PROBE = """
const { CustomizableUI } = ChromeUtils.importESModule(
  "moz-src:///browser/components/customizableui/CustomizableUI.sys.mjs"
);
return CustomizableUI.getWidgetIdsInArea("TabsToolbar");
"""


def tabstrip_after_startup(binary: Path, version: int) -> list:
    state = {
        "placements": {
            "nav-bar": ["home-button", "back-button", "forward-button", "stop-reload-button",
                        "customizableui-special-spring1", "vertical-spacer", "urlbar-container",
                        "customizableui-special-spring2", "downloads-button",
                        "fxa-toolbar-menu-button", "reset-pbm-toolbar-button",
                        "unified-extensions-button"],
            "TabsToolbar": TABSTRIP,
            "toolbar-menubar": ["menubar-items"],
            "PersonalToolbar": ["personal-bookmarks"],
            "vertical-tabs": [],
            "widget-overflow-fixed-list": [],
            "unified-extensions-area": [],
        },
        "seen": ["reset-pbm-toolbar-button", "ai-window-toggle", "developer-button",
                 "smartwindow-group-tabs-button"],
        "dirtyAreaCache": [],
        "currentVersion": version,
        "newElementCount": 3,
    }
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="aliasmode-toolbar-") as tmp:
        (Path(tmp) / "user.js").write_text(
            f'user_pref("marionette.port", {port});\n'
            f'user_pref("browser.uiCustomization.state", {json.dumps(json.dumps(state))});\n',
            encoding="utf-8",
        )
        proc = subprocess.Popen(
            [str(binary), "--headless", "--no-remote", "--profile", tmp, *marionette_args()],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=marionette_env(),
        )
        client = None
        try:
            client = Marionette(port)
            return client.js(PROBE)
        finally:
            if client:
                client.close()
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def main() -> int:
    binary = resolve_binary()
    from_156 = tabstrip_after_startup(binary, 27)
    from_159 = tabstrip_after_startup(binary, 28)
    print(f"saved by AliasMode 156: {from_156}")
    print(f"saved by Firefox 159:   {from_159}")
    failures = []
    if from_156 != STOCK_159:
        failures.append(f"AliasMode 156 state did not take step 27: expected {STOCK_159}")
    if from_159 != TABSTRIP:
        failures.append(f"a version 28 state was migrated again: expected {TABSTRIP}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: AliasMode 156 toolbars upgrade as stock 156 toolbars do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
