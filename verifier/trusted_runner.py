"""Fixed trusted browser acceptance suite, executed only inside the verifier image.

Candidate content is served as static bytes. It is never imported or executed by
Python. The browser has no external network and runs as an unprivileged container
user. Chromium's process sandbox is disabled; Docker is the isolation boundary.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
from pathlib import Path
import sys
import threading
import time

from playwright.sync_api import sync_playwright

# -I excludes the script directory; only this trusted, immutable mount is added.
sys.path.insert(0, str(Path(__file__).resolve().parent))


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=("static-web", "local-notes", "local-inventory"))
    args = parser.parse_args()
    from accessibility import common_accessibility_checks, static_web_accessibility_checks
    if args.profile == "static-web":
        from task_checks import CHECKS
        selected_checks = CHECKS + static_web_accessibility_checks()
    elif args.profile == "local-notes":
        from notes_checks import CHECKS, seed_for_accessibility
        selected_checks = CHECKS + common_accessibility_checks(seed_for_accessibility)
    else:
        from inventory_checks import CHECKS, seed_for_accessibility
        selected_checks = CHECKS + common_accessibility_checks(seed_for_accessibility)
    started = time.monotonic()
    checks = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory="/candidate"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, chromium_sandbox=False,
                                                 args=["--disable-dev-shm-usage"])
            for name, check in selected_checks:
                context = browser.new_context(viewport={"width": 1024, "height": 768},
                                              service_workers="block")
                page = context.new_page()
                page.set_default_timeout(2500)
                page.set_default_navigation_timeout(5000)
                try:
                    # Defense in depth; Docker network=none is the actual egress boundary.
                    page.route("**/*", lambda route: route.continue_()
                               if route.request.url.startswith(origin + "/") else route.abort())
                    page.goto(origin + "/index.html", wait_until="domcontentloaded")
                    observations = check(page)
                    checks.append({"name": name, "passed": True, "detail": "Observed in Chromium",
                                   **({"observations": observations} if isinstance(observations, dict) else {})})
                except Exception as exc:
                    checks.append({"name": name, "passed": False,
                                   "detail": str(exc).split("Call log:")[0][:600]})
                finally:
                    context.close()
            browser.close()
    except Exception as exc:
        checks.append({"name": "browser_runtime", "passed": False, "detail": str(exc)[:600]})
    finally:
        server.shutdown()
        server.server_close()
    print(json.dumps({"passed": len(checks) == len(selected_checks) and all(c["passed"] for c in checks),
                      "checks": checks, "runner": "trusted-playwright-profiles-v2",
                      "browser_process_sandbox": False,
                      "duration_ms": round((time.monotonic() - started) * 1000)}))


if __name__ == "__main__":
    main()
