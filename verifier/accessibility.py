"""Bounded browser accessibility checks, not a WCAG conformance certification.

Only import browser dependencies inside browser checks: pure report validation can
be tested without running candidate JavaScript on the host. All browser execution
belongs inside GraphOS's unprivileged, offline verifier container.
"""
from pathlib import Path


AXE_VERSION = "4.14.0"
AXE_SCRIPT = Path(__file__).resolve().parent / "vendor" / "axe-core" / "axe.min.js"
AXE_TAGS = ("wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa")


def validate_axe_report(report, state_name):
    """Unresolved automated findings need review; they are never passing evidence."""
    assert isinstance(report, dict), "axe did not return an object"
    assert report.get("version") == AXE_VERSION, "Unexpected axe engine version"
    for field in ("violations", "incomplete", "passes", "inapplicable"):
        assert isinstance(report.get(field), list), f"Missing axe {field} results"
    rule_ids = {item.get("id") for field in ("violations", "incomplete", "passes", "inapplicable")
                for item in report[field] if isinstance(item, dict)}
    assert "color-contrast" in rule_ids, "axe omitted the required color-contrast rule"
    findings = []
    for field in ("violations", "incomplete"):
        for item in report[field]:
            targets = [str(node.get("target", "?")) for node in item.get("nodes", [])[:2]]
            findings.append(f"{field}:{item.get('id', '?')} at {', '.join(targets)}")
    assert not findings, f"axe {state_name}: " + "; ".join(findings)[:550]
    return {"engine": f"axe-core@{AXE_VERSION}", "state": state_name,
            "rules_passed": len(report["passes"]), "violations": 0, "incomplete": 0}


def axe_audit(page, state_name="current"):
    page.evaluate("async () => { await document.fonts.ready; }")
    page.add_script_tag(path=str(AXE_SCRIPT))
    report = page.evaluate("""async tags => {
      if (!window.axe || typeof window.axe.run !== 'function') throw Error('axe unavailable');
      const result = await Promise.race([
        window.axe.run(document, {runOnly: {type: 'tag', values: tags},
          rules: {'color-contrast': {enabled: true}}, reporter: 'v2'}),
        new Promise((_, reject) => setTimeout(() => reject(Error('axe audit timed out')), 12000))
      ]);
      const summarize = values => values.map(item => ({id: item.id,
        nodes: item.nodes.map(node => ({target: node.target}))}));
      return {version: result.testEngine.version, violations: summarize(result.violations),
        incomplete: summarize(result.incomplete), passes: summarize(result.passes),
        inapplicable: summarize(result.inapplicable)};
    }""", list(AXE_TAGS))
    return validate_axe_report(report, state_name)


def tab_to(page, locator, max_tabs=60):
    """Reach a target using actual Tab events, never locator.focus()."""
    assert locator.count() == 1 and locator.is_visible(), "Keyboard target is missing or hidden"
    for _ in range(max_tabs):
        if locator.evaluate("el => el === document.activeElement"):
            return
        page.keyboard.press("Tab")
    raise AssertionError("Control cannot be reached with Tab within the bounded traversal")


def assert_keyboard_reachable(page, locators):
    for locator in locators:
        tab_to(page, locator)


def assert_visible_focus(page, locator):
    """Profile contract: a >=2 CSS px focus outline, >=3:1 adjacent contrast.

    This deliberately supports an explicit outline rather than treating a small
    screenshot difference, shadow, or a scripted focus flag as sufficient proof.
    It does not certify every WCAG focus appearance criterion.
    """
    tab_to(page, locator)
    result = locator.evaluate(r"""el => {
      const style = getComputedStyle(el);
      const rgba = color => {
        const m = color.match(/^rgba?\(([^)]+)\)$/);
        if (!m) return null;
        const values = m[1].split(/[, /]+/).filter(Boolean).map(Number);
        return values.length === 3 ? [...values, 1] : values;
      };
      const luminance = color => color.slice(0, 3).map(v => v / 255)
        .map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
        .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
      // A positive outline offset is painted over ancestors, not the control's fill.
      let background = [255, 255, 255, 1];
      let transparent = false;
      for (let node = el.parentElement; node; node = node.parentElement) {
        const s = getComputedStyle(node), color = rgba(s.backgroundColor);
        if (s.backgroundImage !== 'none') return {reason: 'Complex focus background needs review'};
        if (!color) return {reason: 'Unresolved focus background color'};
        if (color[3] === 1) { background = color; break; }
        if (color[3] !== 0) transparent = true;
      }
      const foreground = rgba(style.outlineColor);
      if (transparent || !foreground || foreground[3] !== 1)
        return {reason: 'Translucent focus contrast needs review'};
      const a = luminance(foreground), b = luminance(background);
      const contrast = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
      const rect = el.getBoundingClientRect();
      const offset = parseFloat(style.outlineOffset), width = parseFloat(style.outlineWidth);
      if (offset < 0) return {reason: 'Inset focus outline needs review'};
      const extent = offset + width;
      for (let node = el.parentElement; node; node = node.parentElement) {
        const s = getComputedStyle(node), r = node.getBoundingClientRect();
        if ((/(hidden|clip|scroll|auto)/.test(s.overflowX) &&
             (rect.left - extent < r.left || rect.right + extent > r.right)) ||
            (/(hidden|clip|scroll|auto)/.test(s.overflowY) &&
             (rect.top - extent < r.top || rect.bottom + extent > r.bottom)))
          return {reason: 'Focus outline is clipped by an ancestor'};
      }
      const point = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
      return {width, style: style.outlineStyle, contrast,
        visible: !!point && (point === el || el.contains(point)),
        viewport: rect.left - extent >= 0 && rect.right + extent <= innerWidth};
    }""")
    assert not result.get("reason"), result.get("reason")
    assert result["style"] not in ("none", "hidden") and result["width"] >= 2, \
        "Keyboard focus requires a visible outline at least 2 CSS pixels wide"
    assert result["contrast"] >= 3, "Focus outline contrast is below 3:1"
    assert result["visible"] and result["viewport"], "Keyboard focus is obscured or offscreen"


def assert_mobile_reflow(page):
    """Check 320 and 390 CSS pixel layouts including text and control bounds."""
    for width in (320, 390):
        page.set_viewport_size({"width": width, "height": 844})
        page.evaluate("async () => { await document.fonts.ready; }")
        result = page.evaluate("""() => {
          const viewport = document.documentElement.clientWidth;
          const tooWide = Math.max(document.documentElement.scrollWidth,
            document.body.scrollWidth) > viewport + 1;
          const outside = [];
          const visible = el => el.getClientRects().length &&
            getComputedStyle(el).visibility !== 'hidden';
          for (const el of document.querySelectorAll('input,button,select,textarea,a[href]')) {
            if (!visible(el)) continue;
            const r = el.getBoundingClientRect();
            if (r.left < -1 || r.right > viewport + 1 || r.width < 1 || r.height < 1)
              outside.push(el.tagName + ':' + (el.getAttribute('aria-label') || el.textContent).slice(0, 50));
          }
          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          while (walker.nextNode()) {
            const node = walker.currentNode, parent = node.parentElement;
            if (!node.textContent.trim() || !parent || !visible(parent) ||
                ['SCRIPT','STYLE','NOSCRIPT'].includes(parent.tagName)) continue;
            const range = document.createRange(); range.selectNodeContents(node);
            for (const r of range.getClientRects())
              if (r.width && (r.left < -1 || r.right > viewport + 1))
                outside.push('text:' + node.textContent.trim().slice(0, 50));
          }
          return {tooWide, outside: outside.slice(0, 5)};
        }""")
        assert not result["tooWide"] and not result["outside"], \
            f"Mobile reflow failed at {width}px: {result}"


def _add(page, text):
    page.get_by_role("textbox", name="New task", exact=True).fill(text)
    page.get_by_role("button", name="Add task", exact=True).click()


def _seed(page, completed=False):
    _add(page, "Review accessibility")
    _add(page, "Plan next milestone")
    if completed:
        page.get_by_role("checkbox", name="Review accessibility", exact=True).check()


def _empty(page):
    return axe_audit(page, "empty")


def _populated(page):
    _seed(page)
    return axe_audit(page, "populated")


def _completed(page):
    _seed(page, completed=True)
    return axe_audit(page, "completed")


def _keyboard(page):
    from playwright.sync_api import expect

    textbox = page.get_by_role("textbox", name="New task", exact=True)
    for text in ("Keyboard active", "Keyboard completed"):
        tab_to(page, textbox)
        page.keyboard.type(text)
        tab_to(page, page.get_by_role("button", name="Add task", exact=True))
        page.keyboard.press("Enter")
        expect(page.get_by_role("checkbox", name=text, exact=True)).to_be_visible()
    checkbox = page.get_by_role("checkbox", name="Keyboard completed", exact=True)
    tab_to(page, checkbox)
    page.keyboard.press("Space")
    expect(checkbox).to_be_checked()
    for name, visible, hidden in (("Active", "Keyboard active", "Keyboard completed"),
                                  ("Completed", "Keyboard completed", "Keyboard active")):
        tab_to(page, page.get_by_role("button", name=name, exact=True))
        page.keyboard.press("Enter")
        expect(page.get_by_role("checkbox", name=visible, exact=True)).to_be_visible()
        expect(page.get_by_role("checkbox", name=hidden, exact=True)).not_to_be_visible()
    tab_to(page, page.get_by_role("button", name="All", exact=True))
    page.keyboard.press("Space")
    expect(page.get_by_role("checkbox", name="Keyboard active", exact=True)).to_be_visible()
    tab_to(page, checkbox)
    page.keyboard.press("Space")
    expect(checkbox).not_to_be_checked()
    tab_to(page, page.get_by_role("button", name="Delete Keyboard active", exact=True))
    page.keyboard.press("Enter")
    expect(page.get_by_role("checkbox", name="Keyboard active", exact=True)).to_have_count(0)
    expect(checkbox).to_be_visible()


def _focus(page):
    _seed(page, completed=True)
    controls = [page.get_by_role("textbox", name="New task", exact=True)]
    controls.extend(page.get_by_role("button", name=name, exact=True)
                    for name in ("Add task", "All", "Active", "Completed"))
    for text in ("Review accessibility", "Plan next milestone"):
        controls.extend((page.get_by_role("checkbox", name=text, exact=True),
                         page.get_by_role("button", name="Delete " + text, exact=True)))
    for control in controls:
        assert_visible_focus(page, control)


def _mobile(page):
    _seed(page, completed=True)
    _add(page, "LongTask" * 25)
    assert_mobile_reflow(page)


def static_web_accessibility_checks():
    return [("axe_empty", _empty), ("axe_populated", _populated), ("axe_completed", _completed),
            ("keyboard_operation", _keyboard), ("visible_focus", _focus),
            ("mobile_reflow", _mobile)]


def _controls(page):
    candidates = page.locator("input:not([type=hidden]),button,select,textarea,a[href],[tabindex]")
    controls = [candidates.nth(index) for index in range(candidates.count())
                if candidates.nth(index).is_visible() and candidates.nth(index).is_enabled()]
    assert controls, "No interactive controls found for accessibility checks"
    assert len(controls) <= 40, "Interactive control count exceeds this profile's bounded traversal"
    return controls


def common_accessibility_checks(seed_for_accessibility):
    """Shared finite checks for profiles that provide a trusted populated-state seed.

    Product verifiers own their semantic keyboard activation checks; this factory
    checks keyboard reachability of the visible controls as well as their focus.
    """
    def populated(page):
        seed_for_accessibility(page)
        return axe_audit(page, "populated")

    def keyboard(page):
        seed_for_accessibility(page)
        assert_keyboard_reachable(page, _controls(page))

    def focus(page):
        seed_for_accessibility(page)
        for control in _controls(page):
            assert_visible_focus(page, control)

    def mobile(page):
        seed_for_accessibility(page)
        assert_mobile_reflow(page)

    return [("axe_empty", _empty), ("axe_populated", populated),
            ("keyboard_navigation", keyboard), ("visible_focus", focus),
            ("mobile_reflow", mobile)]
