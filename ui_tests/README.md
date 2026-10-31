# Web App browser tests

Automated tests that use the Web App the way a person does: they open it in a
real browser (Playwright), pick a user, fill in forms and click buttons, then
check both what the page shows and what the Core API stored.

They run against the Docker stack and **wipe its database before every test**
(through the Core API's `/reset`).

## Set up once

```powershell
pip install -r ui_tests/requirements.txt
python -m playwright install chromium
```

Only the tests need this; the Web App and its container stay dependency-free.

## Run

```powershell
docker compose up -d --build                       # from the repo root
python -m unittest discover -s ui_tests -v         # all tests, headless
python -m unittest discover -s ui_tests -p "test_tickets.py" -v   # one file
```

To watch the browser while the tests run (PowerShell):

```powershell
$env:HEADED = "1"; $env:SLOWMO = "300"
python -m unittest discover -s ui_tests -v
Remove-Item Env:HEADED, Env:SLOWMO
```

When a test fails, a screenshot and a Playwright trace are saved in
`ui_tests/artifacts/` (ignored by git). Open a trace to see every step, the
page at that moment and the network calls:

```powershell
python -m playwright show-trace ui_tests/artifacts/<test name>.zip
```

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `WEB_URL` | `http://localhost:8000` | Web App |
| `CORE_URL` | `http://localhost:3001` | Core API (used to reset the database and check results) |
| `HEADED` | off | `1` shows the browser window |
| `SLOWMO` | `0` | Milliseconds to pause between browser actions |
| `BROWSER` | `chromium` | `firefox` or `webkit` also work (install them with `playwright install`) |
| `UI_TIMEOUT_MS` | `10000` | How long to wait for an element |
| `UI_ALLOW_REMOTE` | off | The tests refuse non-localhost URLs, because they wipe the database. `1` allows them. |

## What's covered

| File | Workflows |
|---|---|
| `test_signin_and_navigation.py` | Sign-in prompt, choosing a user, hidden service account, sign-in remembered, navigation, Core API status |
| `test_incidents.py` | Reporting an incident (all fields, chosen ID, required description, cancel), long descriptions with "Show more", the incident list, opening by ID, unknown ID, editing details, unregistered dependency |
| `test_tickets.py` | Logging a ticket, required details, updating (new version), full log of every version, notifying teams, claiming, audit entries |
| `test_decisions.py` | Material and immaterial decisions, required rationale, the 8-K view |
| `test_queue_and_dependencies.py` | Team queue for another user, claiming from the queue, adding, checking and removing dependencies (with confirmation), duplicates, linking an incident to a dependency |
| `test_accessibility.py` | The accessibility checklist (WCAG 2.x): text contrast, visible focus on every element, form-field borders, labels, alt text, one heading and a title per page, focus moving to new content, incidents opened by a real link, announcements, reporting an incident with the keyboard only, and a full axe-core scan |

## Accessibility checks

`test_accessibility.py` follows the project's accessibility checklist
(`Website Accessibility Checklist.pdf`). The contrast, focus, label, heading and
keyboard checks run in the browser with no extra installs.

The axe scan does what the checklist's Axe DevTools step does. It downloads
axe-core from cdnjs when it runs; without internet it's skipped. To use a local
copy, set `AXE_URL` to its location, e.g. `file:///C:/tools/axe.min.js`.

Two checklist items still need a person:

* **Colour alone (item 1):** view the pages in grayscale (Chrome DevTools →
  Rendering → "Emulate vision deficiencies" → Achromatopsia) and check
  everything still makes sense.
* **Screen reader (item 12):** with NVDA (free, Windows), report an incident,
  log and claim a ticket, and record a decision without looking at the screen.

## Writing more tests

* Subclass `UITestCase` from `ui_base.py`. Each test starts signed in as
  `alice` (CYBER1) on an empty database; set `user = "bob"` on the class, or
  call `self.sign_in("bob")` mid-test. Users come from
  `web_app/config/settings.json`.
* Find elements with `self.tid("<data-testid>")`. The attributes are in
  `web_app/secheck_web/static/index.html` and `app.js`; add one when a test
  needs a new element, and keep them when changing the markup.
* Helpers: `report_incident(...)`, `log_ticket(...)`, `ticket_item(number)`,
  `expect_notice(text, kind="ok"|"error")`, and `self.core` for Core API reads
  (`incident`, `ticket`, `log`, `incidents`, `dependency_exists`).
* `python -m playwright codegen http://localhost:8000/app/` opens a browser and
  writes code as you click, which is a quick way to draft a new test.
