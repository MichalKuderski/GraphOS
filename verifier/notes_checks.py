"""Trusted checks for the fixed offline notes product contract.

Invoked only by the isolated browser runner. Each check gets a fresh page and
browser context; this module never reads or imports candidate code.
"""
from playwright.sync_api import expect


def create(page, title, body):
    page.get_by_role("textbox", name="Note title", exact=True).fill(title)
    page.get_by_role("textbox", name="Note body", exact=True).fill(body)
    page.get_by_role("button", name="Save note", exact=True).click()


def row(page, title):
    return page.get_by_test_id("note-item").filter(
        has=page.get_by_role("heading", name=title, exact=True))


def assert_note(page, title, body):
    expect(row(page, title)).to_be_visible()
    expect(row(page, title).get_by_test_id("note-body")).to_have_text(body)
    assert row(page, title).get_by_test_id("note-body").text_content() == body, \
        "The saved note body changed whitespace or text"


def start_edit(page, title):
    row(page, title).get_by_role("button", name="Edit " + title, exact=True).click()


def structure(page):
    expect(page.get_by_role("main")).to_be_visible()
    expect(page.get_by_role("heading").first).to_be_visible()
    for label in ("Note title", "Note body", "Search notes"):
        expect(page.get_by_role("textbox", name=label, exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Save note", exact=True)).to_be_visible()


def creation(page):
    create(page, "Project outline", "Investigate the problem.\nSketch a small solution.")
    assert_note(page, "Project outline", "Investigate the problem.\nSketch a small solution.")
    expect(page.get_by_test_id("note-item")).to_have_count(1)
    create(page, "Reading list", "Read the specification.")
    assert_note(page, "Reading list", "Read the specification.")
    expect(page.get_by_test_id("note-item")).to_have_count(2)


def editing(page):
    create(page, "Draft plan", "First version")
    create(page, "Keep unchanged", "An independent note")
    start_edit(page, "Draft plan")
    expect(page.get_by_role("textbox", name="Note title", exact=True)).to_have_value("Draft plan")
    expect(page.get_by_role("textbox", name="Note body", exact=True)).to_have_value("First version")
    create(page, "Reviewed plan", "Second version\nReady to discuss")
    expect(row(page, "Draft plan")).to_have_count(0)
    assert_note(page, "Reviewed plan", "Second version\nReady to discuss")
    assert_note(page, "Keep unchanged", "An independent note")
    expect(page.get_by_test_id("note-item")).to_have_count(2)


def cancellation(page):
    create(page, "Saved plan", "Original details")
    start_edit(page, "Saved plan")
    page.get_by_role("textbox", name="Note title", exact=True).fill("Unsaved title")
    page.get_by_role("textbox", name="Note body", exact=True).fill("Unsaved body")
    page.get_by_role("button", name="Cancel editing", exact=True).click()
    assert_note(page, "Saved plan", "Original details")
    expect(row(page, "Unsaved title")).to_have_count(0)
    create(page, "A separate note", "A new draft after canceling")
    assert_note(page, "Saved plan", "Original details")
    assert_note(page, "A separate note", "A new draft after canceling")
    expect(page.get_by_test_id("note-item")).to_have_count(2)


def searching(page):
    create(page, "Orchid research", "Water weekly")
    create(page, "Shopping", "Remember ORCHID pots")
    create(page, "Travel plans", "Book a train")
    search = page.get_by_role("textbox", name="Search notes", exact=True)
    search.fill("oRcHiD")
    expect(row(page, "Orchid research")).to_be_visible()
    expect(row(page, "Shopping")).to_be_visible()
    expect(row(page, "Travel plans")).not_to_be_visible()
    search.fill("unmatched phrase")
    expect(page.get_by_test_id("note-item").filter(visible=True)).to_have_count(0)
    search.fill("   ")
    for title in ("Orchid research", "Shopping", "Travel plans"):
        expect(row(page, title)).to_be_visible()
    search.fill("")
    expect(page.get_by_test_id("note-item").filter(visible=True)).to_have_count(3)


def deletion(page):
    create(page, "Remove this note", "No longer needed")
    create(page, "Keep this note", "Still useful")
    row(page, "Remove this note").get_by_role("button", name="Delete Remove this note", exact=True).click()
    expect(row(page, "Remove this note")).to_have_count(0)
    assert_note(page, "Keep this note", "Still useful")


def persistence(page):
    create(page, "Remember the draft", "Before editing")
    create(page, "Keep a second note", "Independent details")
    start_edit(page, "Remember the draft")
    create(page, "Remember the revision", "After editing\nWith another line")
    assert page.evaluate("localStorage.length") > 0, "No localStorage persistence was written"
    page.reload(wait_until="domcontentloaded")
    assert_note(page, "Remember the revision", "After editing\nWith another line")
    assert_note(page, "Keep a second note", "Independent details")
    expect(row(page, "Remember the draft")).to_have_count(0)
    expect(page.get_by_test_id("note-item")).to_have_count(2)
    row(page, "Keep a second note").get_by_role("button", name="Delete Keep a second note", exact=True).click()
    page.reload(wait_until="domcontentloaded")
    assert_note(page, "Remember the revision", "After editing\nWith another line")
    expect(row(page, "Keep a second note")).to_have_count(0)
    expect(page.get_by_test_id("note-item")).to_have_count(1)


def assert_validation_message(page):
    messages = page.locator('[role="status"], [role="alert"]').filter(visible=True)
    assert any(any(word in message.inner_text().lower()
                   for word in ("required", "empty", "blank", "title", "body", "fill", "enter", "field"))
               for message in messages.all()), "No visible explanation of missing note fields"


def empty_input(page):
    for title, body in (("", "Body"), ("   ", "Body"), ("Title", ""), ("Title", " \n ")):
        create(page, title, body)
        expect(page.get_by_test_id("note-item")).to_have_count(0)
        assert_validation_message(page)
    create(page, "Keep the original", "Original body")
    for title, body in (("   ", "Changed body"), ("Changed title", " \n ")):
        start_edit(page, "Keep the original")
        create(page, title, body)
        assert_note(page, "Keep the original", "Original body")
        expect(page.get_by_test_id("note-item")).to_have_count(1)
        assert_validation_message(page)
    page.reload(wait_until="domcontentloaded")
    assert_note(page, "Keep the original", "Original body")


def assert_no_injection(page):
    expect(page.locator('[data-graphos-injected]')).to_have_count(0)
    assert page.evaluate("typeof window.GRAPHOS_INJECTED") == "undefined", "Note text executed HTML"


def literal_input(page):
    title = '<img data-graphos-injected src=x onerror="window.GRAPHOS_INJECTED=1">'
    body = '<svg data-graphos-injected onload="window.GRAPHOS_INJECTED=1"></svg>\n<strong>Literal text</strong>'
    create(page, title, body)
    assert_note(page, title, body)
    assert_no_injection(page)
    page.get_by_role("textbox", name="Search notes", exact=True).fill("<svg")
    assert_note(page, title, body)
    assert_no_injection(page)
    page.get_by_role("textbox", name="Search notes", exact=True).fill("")
    start_edit(page, title)
    expect(page.get_by_role("textbox", name="Note title", exact=True)).to_have_value(title)
    expect(page.get_by_role("textbox", name="Note body", exact=True)).to_have_value(body)
    edited_title = '<b data-graphos-injected>Edited title</b>'
    edited_body = '<img data-graphos-injected src=y onerror="window.GRAPHOS_INJECTED=1">'
    create(page, edited_title, edited_body)
    assert_note(page, edited_title, edited_body)
    assert_no_injection(page)
    page.reload(wait_until="domcontentloaded")
    assert_note(page, edited_title, edited_body)
    assert_no_injection(page)


def seed_for_accessibility(page):
    """Exercise populated and editing states for shared accessibility checks."""
    create(page, "A thought worth keeping", "Capture one small observation.\nDecide what to try next.")
    create(page, "Notes for tomorrow", "Review the plan, then make time for a break.")
    create(page, "Unbroken" + "n" * 110, "A long title must remain readable on a small screen.")
    start_edit(page, "A thought worth keeping")
    create(page, "A thought worth exploring", "An edited note with a clearer next step.")
    start_edit(page, "Notes for tomorrow")


def tab_to(page, target):
    for _ in range(60):
        page.keyboard.press("Tab")
        if target.evaluate("element => element === document.activeElement"):
            return
    raise AssertionError("A note control could not be reached with Tab")


def keyboard_operations(page):
    title_input = page.get_by_role("textbox", name="Note title", exact=True)
    body_input = page.get_by_role("textbox", name="Note body", exact=True)
    tab_to(page, title_input)
    page.keyboard.insert_text("Keyboard note")
    tab_to(page, body_input)
    page.keyboard.insert_text("Created without pointer input")
    tab_to(page, page.get_by_role("button", name="Save note", exact=True))
    page.keyboard.press("Enter")
    assert_note(page, "Keyboard note", "Created without pointer input")
    tab_to(page, page.get_by_role("button", name="Edit Keyboard note", exact=True))
    page.keyboard.press("Enter")
    expect(title_input).to_have_value("Keyboard note")
    expect(body_input).to_have_value("Created without pointer input")
    tab_to(page, page.get_by_role("button", name="Cancel editing", exact=True))
    page.keyboard.press("Enter")
    assert_note(page, "Keyboard note", "Created without pointer input")
    expect(page.get_by_role("button", name="Cancel editing", exact=True)).not_to_be_visible()


CHECKS = [
    ("accessible_structure", structure), ("create_note", creation),
    ("edit_note", editing), ("cancel_edit", cancellation), ("search_notes", searching),
    ("delete_note", deletion), ("local_storage_reload", persistence),
    ("reject_empty_input", empty_input), ("literal_html_input", literal_input),
    ("keyboard_note_operations", keyboard_operations),
]
