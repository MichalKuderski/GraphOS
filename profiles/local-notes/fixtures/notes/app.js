'use strict';

const STORAGE_KEY = 'graphos.local-notes.v1';
const form = document.querySelector('#note-form');
const titleInput = document.querySelector('#note-title');
const bodyInput = document.querySelector('#note-body');
const searchInput = document.querySelector('#search-notes');
const cancelButton = document.querySelector('#cancel-edit');
const editorHeading = document.querySelector('#editor-heading');
const list = document.querySelector('#notes-list');
const status = document.querySelector('#status');
let editingId = null;
let notes = [];

function announce(message, isError = false) {
  status.textContent = message;
  status.classList.toggle('error', isError);
}

try {
  const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
  if (!Array.isArray(stored) || stored.some(note => !note ||
      typeof note.id !== 'string' || typeof note.title !== 'string' ||
      typeof note.body !== 'string' || !note.title.trim() || !note.body.trim()) ||
      new Set(stored.map(note => note.id)).size !== stored.length) {
    throw new Error('Invalid saved notes');
  }
  notes = stored;
} catch {
  announce('Saved notes could not be loaded. Browser storage may be unavailable or damaged.', true);
}

function commit(nextNotes) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(nextNotes));
    notes = nextNotes;
    return true;
  } catch {
    announce('This change could not be saved. Check browser storage and keep a separate copy.', true);
    return false;
  }
}

function resetEditor() {
  editingId = null;
  form.reset();
  titleInput.removeAttribute('aria-invalid');
  bodyInput.removeAttribute('aria-invalid');
  editorHeading.textContent = 'New note';
  cancelButton.hidden = true;
}

function startEditing(note) {
  editingId = note.id;
  titleInput.value = note.title;
  bodyInput.value = note.body;
  titleInput.removeAttribute('aria-invalid');
  bodyInput.removeAttribute('aria-invalid');
  editorHeading.textContent = 'Edit note';
  cancelButton.hidden = false;
  announce('Editing “' + note.title + '”. Save your changes or cancel editing.');
  titleInput.focus();
}

function render() {
  list.replaceChildren();
  const query = searchInput.value.trim().toLocaleLowerCase();
  const visible = notes.filter(note => (note.title + '\n' + note.body).toLocaleLowerCase().includes(query));
  for (const note of visible) {
    const article = document.createElement('article');
    article.className = 'note';
    article.dataset.testid = 'note-item';
    const heading = document.createElement('h3');
    heading.textContent = note.title;
    const body = document.createElement('p');
    body.className = 'note-body';
    body.dataset.testid = 'note-body';
    body.textContent = note.body;
    const actions = document.createElement('div');
    actions.className = 'note-actions';
    const editButton = document.createElement('button');
    editButton.type = 'button';
    editButton.textContent = 'Edit';
    editButton.setAttribute('aria-label', 'Edit ' + note.title);
    editButton.addEventListener('click', () => startEditing(note));
    const deleteButton = document.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'danger';
    deleteButton.textContent = 'Delete';
    deleteButton.setAttribute('aria-label', 'Delete ' + note.title);
    deleteButton.addEventListener('click', () => {
      if (!commit(notes.filter(item => item.id !== note.id))) return;
      if (editingId === note.id) resetEditor();
      render();
      announce('Deleted “' + note.title + '”.');
      searchInput.focus();
    });
    actions.append(editButton, deleteButton);
    article.append(heading, body, actions);
    list.append(article);
  }
  document.querySelector('#note-count').textContent = notes.length + (notes.length === 1 ? ' note' : ' notes');
  const empty = document.querySelector('#empty-state');
  empty.hidden = visible.length !== 0;
  empty.textContent = query ? 'No notes match your search. Try another word.' : 'Your next idea belongs here. Create a note to get started.';
}

form.addEventListener('submit', event => {
  event.preventDefault();
  const title = titleInput.value.trim();
  const body = bodyInput.value.trim();
  titleInput.setAttribute('aria-invalid', String(!title));
  bodyInput.setAttribute('aria-invalid', String(!body));
  if (!title || !body) {
    announce('A note needs both a title and a body. Please fill in both fields.', true);
    (!title ? titleInput : bodyInput).focus();
    return;
  }
  const wasEditing = editingId !== null;
  const nextNotes = wasEditing
    ? notes.map(note => note.id === editingId ? { ...note, title, body } : note)
    : [...notes, { id: crypto.randomUUID(), title, body }];
  if (!commit(nextNotes)) return;
  resetEditor();
  searchInput.value = '';
  render();
  announce(wasEditing ? 'Changes saved.' : 'Note saved.');
  titleInput.focus();
});

cancelButton.addEventListener('click', () => {
  resetEditor();
  announce('Editing canceled. Your saved note is unchanged.');
  titleInput.focus();
});
searchInput.addEventListener('input', render);
render();
