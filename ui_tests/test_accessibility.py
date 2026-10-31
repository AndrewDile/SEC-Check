"""Accessibility checks, following the project's accessibility checklist (WCAG 2.x).

Automated here: text contrast (1.4.3), visible focus with enough contrast (2.4.7, 1.4.11),
form-field border contrast (1.4.11), labels on every control (1.3.1, 4.1.2), alt text (1.1.1),
one <h1> and a descriptive title per page, focus moving to new content, keyboard-only use (2.1.1),
and, when axe-core can be loaded, a full axe scan (WCAG 2.x A/AA rules).

Still manual: colour-alone and alt-text *meaning* (view the page in grayscale), and a pass with a
screen reader (NVDA on Windows). See ui_tests/README.md.
"""
import os
import unittest
import urllib.request

from playwright.sync_api import expect

from ui_base import UITestCase

# Contrast helpers run in the page. Colours come from getComputedStyle (rgb()/rgba()).
JS_HELPERS = r"""
window.__a11y = (() => {
  const parse = c => c.match(/[\d.]+/g).map(Number);
  const lum = c => { const [r, g, b] = parse(c).slice(0, 3).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const opaque = c => { const p = parse(c); return p.length < 4 || p[3] > 0.5; };
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (opaque(c)) return c; } return "rgb(255, 255, 255)"; };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden"; };
  const describe = el => (el.dataset.testid ? `[${el.dataset.testid}] ` : "") + el.tagName.toLowerCase() + " " + (el.textContent || "").trim().slice(0, 40);

  function textContrast() {
    const bad = [], seen = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const el = walker.currentNode.parentElement;
      if (!walker.currentNode.textContent.trim() || seen.has(el) || !visible(el)) continue;
      seen.add(el);
      if (el.closest(":disabled, .sr-only")) continue;           // disabled controls are exempt
      const s = getComputedStyle(el), size = parseFloat(s.fontSize), bold = parseInt(s.fontWeight, 10) >= 700;
      const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
      const r = ratio(s.color, bgOf(el));
      if (r < need) bad.push(`${describe(el)}: ${r.toFixed(2)}:1, needs ${need}:1`);
    }
    return bad;
  }
  function fieldBorders() {
    return [...document.querySelectorAll("input:not([type=checkbox]):not([type=radio]), select, textarea")]
      .filter(visible).filter(el => !el.disabled)
      .map(el => [el, ratio(getComputedStyle(el).borderTopColor, bgOf(el.parentElement))])
      .filter(([, r]) => r < 3).map(([el, r]) => `${describe(el)}: border ${r.toFixed(2)}:1, needs 3:1`);
  }
  function unnamedControls() {
    return [...document.querySelectorAll("input, select, textarea, button, a[href]")].filter(visible).filter(el => {
      const labelled = el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || (el.labels && [...el.labels].some(l => l.textContent.trim()));
      return !labelled && !el.textContent.trim() && !el.getAttribute("title");
    }).map(describe);
  }
  function imagesWithoutAlt() {
    return [...document.querySelectorAll("img")].filter(i => !i.hasAttribute("alt")).map(i => i.src);
  }
  function focusRing() {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    const s = getComputedStyle(el);
    const width = parseFloat(s.outlineWidth) || 0;
    if (s.outlineStyle === "none" || width < 2) return { el: describe(el), ok: false, why: "no outline" };
    const bg = bgOf(el.parentElement), r = ratio(s.outlineColor, bg);
    return { el: describe(el), ok: r >= 3, why: `outline ${r.toFixed(2)}:1 against background` };
  }
  return { textContrast, fieldBorders, unnamedControls, imagesWithoutAlt, focusRing };
})();
"""

AXE_URL = os.environ.get("AXE_URL", "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js")


class Accessibility(UITestCase):
    def setUp(self):
        super().setUp()
        # One incident with every part of the page in use: a ticket, a material decision, the full log.
        self.core.ok("/dependencies", {"dp_name": "okta sso", "method": "NEW"})
        self.iid = self.report_incident("Ransomware encrypted the billing database.", dependency="okta sso")
        self.log_ticket("Contain the billing database.", severity="HIGH", teams=["CYBER1"])
        form = self.tid("decision-form")
        self.tid("decision-materiality", form).select_option("MATERIAL")
        self.tid("decision-rationale", form).fill("Customer payment data affected.")
        self.tid("decision-submit", form).click()
        self.expect_notice("Decision recorded")

    # ------------------------------------------------------------------ helpers
    def pages(self):
        """Visit each page in turn and yield its name. The incident page has the 8-K view and full log open."""
        self.go("#/incidents")
        expect(self.tid("incident-row")).to_have_count(1)
        yield "incident list"
        self.go("#/incidents/" + self.iid)
        self.tid("open-8k").click()
        self.tid("full-log-toggle").click()
        expect(self.tid("log-entry").first).to_be_visible()
        yield "incident detail"
        self.go("#/queue")
        expect(self.tid("queue-form")).to_be_visible()
        yield "team queue"
        self.go("#/dependencies")
        expect(self.tid("dependency-row")).to_have_count(1)
        yield "dependencies"
        self.go("#/incidents/999999999999")
        self.expect_notice("UUID_DNE", kind="error")
        yield "error notice"

    def js(self, check):
        self.page.add_script_tag(content=JS_HELPERS)
        return self.page.evaluate("window.__a11y.%s()" % check)

    def tab_to(self, test_id, presses=80):
        for _ in range(presses):
            self.page.keyboard.press("Tab")
            if self.page.evaluate("document.activeElement && document.activeElement.dataset.testid") == test_id:
                return
        self.fail("couldn't reach %s with the Tab key" % test_id)

    # ------------------------------------------------------------------ checklist items
    def test_text_contrast(self):                                    # checklist 2, SC 1.4.3
        problems = {}
        for name in self.pages():
            bad = self.js("textContrast")
            if bad:
                problems[name] = bad
        self.assertEqual(problems, {})

    def test_form_field_borders_are_visible(self):                  # SC 1.4.11
        problems = {}
        for name in self.pages():
            bad = self.js("fieldBorders")
            if bad:
                problems[name] = bad
        self.assertEqual(problems, {})

    def test_every_control_has_a_label(self):                       # checklist 11, SC 1.3.1 / 4.1.2
        problems = {}
        for name in self.pages():
            bad = self.js("unnamedControls")
            if bad:
                problems[name] = bad
        self.assertEqual(problems, {})

    def test_images_have_alt_text(self):                            # checklist 3, SC 1.1.1
        for name in self.pages():
            self.assertEqual(self.js("imagesWithoutAlt"), [], name)
        expect(self.page.locator("img.footer-logo")).to_have_attribute("alt", "SEC-Check logo")

    def test_focus_is_always_visible(self):                         # checklist 9, SC 2.4.7 / 1.4.11
        problems = []
        for name in self.pages():
            self.page.add_script_tag(content=JS_HELPERS)
            self.page.locator("footer").click(position={"x": 1, "y": 1})   # start tabbing from the page, not a field
            self.page.keyboard.press("Shift+Tab")
            for _ in range(100):
                self.page.keyboard.press("Tab")
                ring = self.page.evaluate("window.__a11y.focusRing()")
                if ring is None:
                    break
                if not ring["ok"]:
                    problems.append("%s: %s (%s)" % (name, ring["el"], ring["why"]))
                if ring["el"].startswith("a API docs"):
                    break
        self.assertEqual(problems, [])

    def test_each_page_has_one_h1_and_its_own_title(self):          # screen-reader navigation
        titles = []
        for name in self.pages():
            expect(self.page.locator("main h1")).to_have_count(1)
            titles.append(self.page.title())
        self.assertEqual(titles, ["Incidents – SEC-Check", "Incident %s – SEC-Check" % self.iid, "Team queue – SEC-Check",
                                  "Dependencies – SEC-Check", "Incident not found – SEC-Check"])

    def test_focus_moves_to_new_content(self):                      # checklist 12, SC 2.4.3
        self.tid("nav-dependencies").click()
        expect(self.page.locator("main h1")).to_be_focused()
        self.tid("nav-incidents").click()
        self.tid("incident-link").first.click()
        expect(self.tid("incident-heading")).to_be_focused()
        expect(self.tid("incident-heading")).to_have_text("Incident %s: Material" % self.iid)
        self.tid("open-8k").click()
        expect(self.tid("form-8k").locator("h2")).to_be_focused()

    def test_incidents_open_from_a_real_link(self):                 # checklist 10 and 12
        self.go("#/incidents")
        link = self.tid("incident-link").first
        expect(link).to_have_attribute("href", "#/incidents/" + self.iid)
        link.focus()
        self.page.keyboard.press("Enter")
        expect(self.tid("incident-id")).to_have_text(self.iid)

    def test_remove_confirmation_is_announced(self):                # checklist 12
        self.go("#/dependencies")
        self.tid("dependency-remove").click()
        expect(self.tid("announcer")).to_have_text("Press Confirm remove to remove okta sso.")

    def test_report_an_incident_with_the_keyboard_only(self):       # checklist 10, SC 2.1.1
        self.go("#/incidents")
        self.page.locator("footer").click(position={"x": 1, "y": 1})
        self.tab_to("new-incident")
        self.page.keyboard.press("Enter")
        self.tab_to("intake-description")
        self.page.keyboard.type("Reported without a mouse.")
        self.tab_to("intake-submit")
        self.page.keyboard.press("Enter")
        self.expect_notice("created")
        expect(self.tid("incident-description")).to_have_text("Reported without a mouse.")

    def test_axe_finds_no_wcag_violations(self):                    # checklist 2, 3, 11 (as Axe DevTools would)
        try:
            with urllib.request.urlopen(AXE_URL, timeout=10) as r:
                axe_js = r.read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            self.skipTest("axe-core couldn't be downloaded from %s (%s); set AXE_URL to a local copy" % (AXE_URL, exc))
        problems = {}
        for name in self.pages():
            self.page.add_script_tag(content=axe_js)
            result = self.page.evaluate("""() => axe.run(document, {
                runOnly: {type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]}})""")
            found = ["%s (%s): %s at %s" % (v["id"], v["impact"], v["help"], ", ".join(str(n["target"]) for n in v["nodes"][:3]))
                     for v in result["violations"]]
            if found:
                problems[name] = found
        self.assertEqual(problems, {})


if __name__ == "__main__":
    unittest.main()
