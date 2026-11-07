"""Fixed trusted browser acceptance suite, executed only inside the verifier image.

Candidate content is served as static bytes. It is never imported or executed by
Python. The browser has no external network and runs as an unprivileged container
user. Chromium's process sandbox is disabled; Docker is the isolation boundary.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

from playwright.sync_api import sync_playwright, expect


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def add(page, text):
    page.get_by_role("textbox", name="New task", exact=True).fill(text)
    page.get_by_role("button", name="Add task", exact=True).click()


def row(page, text):
    return page.get_by_test_id("task-item").filter(
        has=page.get_by_role("checkbox", name=text, exact=True))


def structure(page):
    expect(page.get_by_role("main")).to_be_visible()
    expect(page.get_by_role("heading").first).to_be_visible()
    expect(page.get_by_role("textbox", name="New task", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Add task", exact=True)).to_be_visible()
    for name in ("All", "Active", "Completed"):
        expect(page.get_by_role("button", name=name, exact=True)).to_be_visible()


def addition(page):
    add(page, "Plan project")
    expect(row(page, "Plan project")).to_be_visible()
    expect(page.get_by_test_id("task-item")).to_have_count(1)
    expect(page.get_by_role("checkbox", name="Plan project", exact=True)).not_to_be_checked()


def completion(page):
    add(page, "Complete review")
    checkbox = page.get_by_role("checkbox", name="Complete review", exact=True)
    checkbox.check()
    expect(checkbox).to_be_checked()
    checkbox.uncheck()
    expect(checkbox).not_to_be_checked()


def filters(page):
    add(page, "Active task")
    add(page, "Done task")
    page.get_by_role("checkbox", name="Done task", exact=True).check()
    page.get_by_role("button", name="Active", exact=True).click()
    expect(row(page, "Active task")).to_be_visible()
    expect(row(page, "Done task")).not_to_be_visible()
    page.get_by_role("button", name="Completed", exact=True).click()
    expect(row(page, "Done task")).to_be_visible()
    expect(row(page, "Active task")).not_to_be_visible()
    page.get_by_role("button", name="All", exact=True).click()
    expect(row(page, "Active task")).to_be_visible()
    expect(row(page, "Done task")).to_be_visible()


def deletion(page):
    add(page, "Remove me")
    add(page, "Keep me")
    row(page, "Remove me").get_by_role("button", name="Delete Remove me", exact=True).click()
    expect(row(page, "Remove me")).to_have_count(0)
    expect(row(page, "Keep me")).to_be_visible()


def persistence(page):
    add(page, "Remember completed")
    add(page, "Remember active")
    page.get_by_role("checkbox", name="Remember completed", exact=True).check()
    assert page.evaluate("localStorage.length") > 0, "No localStorage persistence was written"
    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_role("checkbox", name="Remember completed", exact=True)).to_be_checked()
    expect(page.get_by_role("checkbox", name="Remember active", exact=True)).not_to_be_checked()
    row(page, "Remember active").get_by_role("button", name="Delete Remember active", exact=True).click()
    page.reload(wait_until="domcontentloaded")
    expect(row(page, "Remember active")).to_have_count(0)


def empty_input(page):
    add(page, "")
    add(page, "   ")
    expect(page.get_by_test_id("task-item")).to_have_count(0)


def literal_input(page):
    text = '<img src=x onerror="window.GRAPHOS_INJECTED=1">'
    add(page, text)
    expect(page.get_by_text(text, exact=True)).to_be_visible()
    expect(row(page, text)).to_be_visible()
    expect(page.locator('img[src="x"]')).to_have_count(0)
    assert page.evaluate("typeof window.GRAPHOS_INJECTED") == "undefined", "Task input executed HTML"
    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_text(text, exact=True)).to_be_visible()
    assert page.evaluate("typeof window.GRAPHOS_INJECTED") == "undefined", "Reload executed HTML"


CHECKS = [("accessible_structure", structure), ("add_task", addition),
          ("toggle_completion", completion), ("filter_tasks", filters),
          ("delete_task", deletion), ("local_storage_reload", persistence),
          ("reject_empty_input", empty_input), ("literal_html_input", literal_input)]


def main():
    started = time.monotonic()
    checks = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory="/candidate"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, chromium_sandbox=False,
                                                 args=["--disable-dev-shm-usage"])
            for name, check in CHECKS:
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
                    check(page)
                    checks.append({"name": name, "passed": True, "detail": "Observed in Chromium"})
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
    print(json.dumps({"passed": len(checks) == len(CHECKS) and all(c["passed"] for c in checks),
                      "checks": checks, "runner": "trusted-playwright-static-web-v1",
                      "browser_process_sandbox": False,
                      "duration_ms": round((time.monotonic() - started) * 1000)}))


if __name__ == "__main__":
    main()
