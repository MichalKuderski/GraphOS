"""Trusted, bounded local-inventory behavior checks; executed in Docker only."""
from playwright.sync_api import expect


def add(page, name, quantity="1"):
    page.get_by_role("textbox", name="Item name", exact=True).fill(name)
    page.get_by_role("spinbutton", name="Quantity", exact=True).fill(str(quantity))
    page.get_by_role("button", name="Add item", exact=True).click()


def row(page, name):
    return page.get_by_test_id("inventory-item").filter(
        has=page.get_by_role("spinbutton", name="Quantity " + name, exact=True))


def quantity(page, name):
    return row(page, name).get_by_role("spinbutton", name="Quantity " + name, exact=True)


def save(page, name, value):
    quantity(page, name).fill(str(value))
    row(page, name).get_by_role("button", name="Save " + name, exact=True).click()


def seed_for_accessibility(page):
    add(page, "Sketchbooks", "4")
    add(page, "Pencils " + "A" * 75, "0")


def structure(page):
    expect(page.get_by_role("main")).to_be_visible()
    expect(page.get_by_role("heading").first).to_be_visible()
    expect(page.get_by_role("textbox", name="Item name", exact=True)).to_be_visible()
    expect(page.get_by_role("spinbutton", name="Quantity", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Add item", exact=True)).to_be_visible()
    expect(page.get_by_role("searchbox", name="Search items", exact=True)).to_be_visible()


def addition(page):
    add(page, "  Sketchbooks  ", "12")
    add(page, "Pencils", "0")
    expect(page.get_by_test_id("inventory-item")).to_have_count(2)
    expect(row(page, "Sketchbooks")).to_be_visible()
    expect(quantity(page, "Sketchbooks")).to_have_value("12")
    expect(quantity(page, "Pencils")).to_have_value("0")


def editing(page):
    add(page, "Sketchbooks", "12")
    add(page, "Pencils", "8")
    save(page, "Sketchbooks", "24")
    expect(quantity(page, "Sketchbooks")).to_have_value("24")
    expect(quantity(page, "Pencils")).to_have_value("8")
    save(page, "Sketchbooks", "0")
    page.reload(wait_until="domcontentloaded")
    expect(quantity(page, "Sketchbooks")).to_have_value("0")
    expect(quantity(page, "Pencils")).to_have_value("8")


def searching(page):
    add(page, "Blue notebook", "1")
    add(page, "Red notebook", "2")
    add(page, "Pencils", "3")
    search = page.get_by_role("searchbox", name="Search items", exact=True)
    search.fill("BLUE")
    expect(row(page, "Blue notebook")).to_be_visible()
    expect(row(page, "Red notebook")).not_to_be_visible()
    expect(row(page, "Pencils")).not_to_be_visible()
    search.fill("note")
    expect(row(page, "Blue notebook")).to_be_visible()
    expect(row(page, "Red notebook")).to_be_visible()
    expect(row(page, "Pencils")).not_to_be_visible()
    search.fill("no matching item")
    expect(page.get_by_test_id("inventory-item").filter(visible=True)).to_have_count(0)
    search.fill("")
    expect(page.get_by_test_id("inventory-item").filter(visible=True)).to_have_count(3)


def deletion(page):
    add(page, "Remove me", "3")
    add(page, "Keep me", "7")
    row(page, "Remove me").get_by_role("button", name="Delete Remove me", exact=True).click()
    expect(row(page, "Remove me")).to_have_count(0)
    expect(quantity(page, "Keep me")).to_have_value("7")


def persistence(page):
    add(page, "Remember this", "4")
    add(page, "Delete this", "2")
    save(page, "Remember this", "6")
    assert page.evaluate("localStorage.length") > 0, "No localStorage persistence was written"
    page.reload(wait_until="domcontentloaded")
    expect(quantity(page, "Remember this")).to_have_value("6")
    expect(quantity(page, "Delete this")).to_have_value("2")
    row(page, "Delete this").get_by_role("button", name="Delete Delete this", exact=True).click()
    page.reload(wait_until="domcontentloaded")
    expect(row(page, "Delete this")).to_have_count(0)
    expect(quantity(page, "Remember this")).to_have_value("6")


def invalid_input(page):
    for name, value in [("", "1"), ("   ", "1"), ("Empty", ""), ("Negative", "-1"),
                        ("Fractional", "1.5"), ("Unsafe", "9007199254740992")]:
        add(page, name, value)
        expect(page.get_by_test_id("inventory-item")).to_have_count(0)
        expect(page.get_by_role("status")).to_be_visible()
        expect(page.get_by_role("status")).not_to_have_text("")
    add(page, "Keep quantity", "7")
    for value in ("", "-1", "0.5", "9007199254740992"):
        save(page, "Keep quantity", value)
        expect(page.get_by_role("status")).to_be_visible()
        expect(page.get_by_role("status")).not_to_have_text("")
        page.reload(wait_until="domcontentloaded")
        expect(quantity(page, "Keep quantity")).to_have_value("7")
    save(page, "Keep quantity", "0")
    page.reload(wait_until="domcontentloaded")
    expect(quantity(page, "Keep quantity")).to_have_value("0")


def unique_names(page):
    add(page, "Sketchbooks", "7")
    for name in ("Sketchbooks", " sketchbooks ", "SKETCHBOOKS"):
        add(page, name, "999")
        expect(page.get_by_test_id("inventory-item")).to_have_count(1)
        expect(quantity(page, "Sketchbooks")).to_have_value("7")
        expect(page.get_by_role("status")).to_be_visible()
    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_test_id("inventory-item")).to_have_count(1)
    expect(quantity(page, "Sketchbooks")).to_have_value("7")


def literal_input(page):
    name = '<img src=x onerror="window.GRAPHOS_INJECTED=1">'
    add(page, name, "3")
    expect(page.get_by_text(name, exact=True)).to_be_visible()
    expect(quantity(page, name)).to_have_value("3")
    expect(page.locator('img[src="x"]')).to_have_count(0)
    assert page.evaluate("typeof window.GRAPHOS_INJECTED") == "undefined", "Item name executed HTML"
    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_text(name, exact=True)).to_be_visible()
    expect(page.locator('img[src="x"]')).to_have_count(0)
    assert page.evaluate("typeof window.GRAPHOS_INJECTED") == "undefined", "Reload executed HTML"


def keyboard_operation(page):
    from accessibility import tab_to

    def type_into(locator, text):
        tab_to(page, locator)
        page.keyboard.press("Control+a")
        page.keyboard.type(text)

    for name, value in (("Keyboard paper", "5"), ("Keyboard pens", "2")):
        type_into(page.get_by_role("textbox", name="Item name", exact=True), name)
        type_into(page.get_by_role("spinbutton", name="Quantity", exact=True), value)
        tab_to(page, page.get_by_role("button", name="Add item", exact=True))
        page.keyboard.press("Enter")
        expect(row(page, name)).to_be_visible()
    type_into(quantity(page, "Keyboard paper"), "8")
    tab_to(page, page.get_by_role("button", name="Save Keyboard paper", exact=True))
    page.keyboard.press("Enter")
    expect(quantity(page, "Keyboard paper")).to_have_value("8")
    search = page.get_by_role("searchbox", name="Search items", exact=True)
    type_into(search, "paper")
    expect(row(page, "Keyboard paper")).to_be_visible()
    expect(row(page, "Keyboard pens")).not_to_be_visible()
    tab_to(page, search)
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")
    expect(row(page, "Keyboard pens")).to_be_visible()
    tab_to(page, page.get_by_role("button", name="Delete Keyboard paper", exact=True))
    page.keyboard.press("Space")
    expect(row(page, "Keyboard paper")).to_have_count(0)
    expect(quantity(page, "Keyboard pens")).to_have_value("2")


CHECKS = [("accessible_structure", structure), ("add_inventory_item", addition),
          ("edit_quantity", editing), ("search_inventory", searching),
          ("delete_inventory_item", deletion), ("local_storage_reload", persistence),
          ("reject_invalid_input", invalid_input), ("unique_item_names", unique_names),
          ("literal_html_input", literal_input), ("keyboard_operation", keyboard_operation)]
