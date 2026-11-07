'use strict';

const STORAGE_KEY = 'graphos.inventory.v1';
const form = document.querySelector('#add-form');
const nameInput = document.querySelector('#item-name');
const quantityInput = document.querySelector('#quantity');
const searchInput = document.querySelector('#search');
const list = document.querySelector('#inventory-list');
const status = document.querySelector('#status');
const emptyState = document.querySelector('#empty-state');
const count = document.querySelector('#item-count');

function validQuantity(value) {
  if (String(value).trim() === '') return false;
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= 0;
}

function announce(message, error = false) {
  status.textContent = message;
  status.dataset.error = String(error);
}

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    if (!Array.isArray(saved)) throw new Error('Invalid inventory');
    const names = new Set();
    return saved.filter(item => {
      if (!item || typeof item.name !== 'string' || !item.name.trim() ||
          typeof item.quantity !== 'number' || !validQuantity(item.quantity)) return false;
      const key = item.name.trim().toLocaleLowerCase();
      if (names.has(key)) return false;
      names.add(key);
      return true;
    }).map(item => ({ name: item.name.trim(), quantity: item.quantity }));
  } catch {
    announce('Saved inventory could not be read. You can start a new list.', true);
    return [];
  }
}

let items = load();

function persist(next, message) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    announce('Your browser could not save this change. Free some storage and try again.', true);
    return false;
  }
  items = next;
  announce(message);
  render();
  return true;
}

function render() {
  list.replaceChildren();
  const query = searchInput.value.trim().toLocaleLowerCase();
  const visible = items.filter(item => item.name.toLocaleLowerCase().includes(query));
  count.textContent = `${items.length} ${items.length === 1 ? 'item' : 'items'}`;
  emptyState.hidden = visible.length > 0;
  emptyState.textContent = items.length === 0
    ? 'Your shelves are clear. Add your first item above.'
    : 'No matching items. Try a different search.';

  visible.forEach((item, index) => {
    const row = document.createElement('li');
    row.className = 'inventory-row';
    row.dataset.testid = 'inventory-item';
    const description = document.createElement('div');
    const title = document.createElement('p');
    title.className = 'item-name';
    title.textContent = item.name;
    const caption = document.createElement('p');
    caption.className = 'item-caption';
    caption.textContent = item.quantity === 0 ? 'Out of stock' : 'In your stock';
    description.append(title, caption);

    const controls = document.createElement('form');
    controls.className = 'row-controls';
    controls.noValidate = true;
    const field = document.createElement('div');
    field.className = 'field';
    const label = document.createElement('label');
    label.htmlFor = `item-quantity-${index}`;
    label.textContent = 'Quantity';
    const quantity = document.createElement('input');
    Object.assign(quantity, { id: label.htmlFor, type: 'number', min: '0', max: String(Number.MAX_SAFE_INTEGER), step: '1', value: String(item.quantity), required: true });
    quantity.inputMode = 'numeric';
    quantity.setAttribute('aria-label', `Quantity ${item.name}`);
    field.append(label, quantity);
    const save = document.createElement('button');
    save.type = 'submit';
    save.textContent = 'Save';
    save.setAttribute('aria-label', `Save ${item.name}`);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'delete';
    remove.textContent = 'Delete';
    remove.setAttribute('aria-label', `Delete ${item.name}`);

    controls.addEventListener('submit', event => {
      event.preventDefault();
      if (!validQuantity(quantity.value)) {
        announce('Quantity must be a whole number from 0 to 9007199254740991.', true);
        quantity.focus();
        return;
      }
      const next = items.map(candidate => candidate === item
        ? { ...candidate, quantity: Number(quantity.value) } : candidate);
      if (persist(next, `Saved quantity for ${item.name}.`)) {
        const updated = Array.from(list.querySelectorAll('button')).find(button => button.getAttribute('aria-label') === `Save ${item.name}`);
        updated?.focus();
      }
    });
    remove.addEventListener('click', () => {
      if (persist(items.filter(candidate => candidate !== item), `Deleted ${item.name}.`)) searchInput.focus();
    });
    controls.append(field, save, remove);
    row.append(description, controls);
    list.append(row);
  });
}

form.addEventListener('submit', event => {
  event.preventDefault();
  const name = nameInput.value.trim();
  if (!name) {
    announce('Enter an item name.', true);
    nameInput.focus();
    return;
  }
  if (!validQuantity(quantityInput.value)) {
    announce('Quantity must be a whole number from 0 to 9007199254740991.', true);
    quantityInput.focus();
    return;
  }
  if (items.some(item => item.name.toLocaleLowerCase() === name.toLocaleLowerCase())) {
    announce('That item already exists. Edit its quantity below.', true);
    nameInput.focus();
    return;
  }
  if (persist([...items, { name, quantity: Number(quantityInput.value) }], `Added ${name}.`)) {
    nameInput.value = '';
    quantityInput.value = '1';
    nameInput.focus();
  }
});

searchInput.addEventListener('input', render);
render();
