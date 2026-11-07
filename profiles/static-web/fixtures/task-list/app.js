"use strict";
const storageKey = "graphos-task-list-fixture-v1";
let tasks = [];
try {
  const stored = JSON.parse(localStorage.getItem(storageKey) || "[]");
  if (Array.isArray(stored)) tasks = stored.filter(t => t && typeof t.id === "string" && typeof t.text === "string" && typeof t.done === "boolean");
} catch (_) { tasks = []; }
let filter = "all";
const list = document.querySelector("#tasks");
const input = document.querySelector("#new-task");
function save() { localStorage.setItem(storageKey, JSON.stringify(tasks)); }
function render() {
  list.replaceChildren();
  const visible = tasks.filter(t => filter === "all" || (filter === "completed" ? t.done : !t.done));
  for (const task of visible) {
    const item = document.createElement("li"); item.dataset.testid = "task-item";
    const label = document.createElement("label");
    const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.checked = task.done;
    checkbox.addEventListener("change", () => { task.done = checkbox.checked; save(); render(); });
    const text = document.createElement("span"); text.textContent = task.text;
    label.append(checkbox, text);
    const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "Delete";
    remove.setAttribute("aria-label", "Delete " + task.text);
    remove.addEventListener("click", () => { tasks = tasks.filter(t => t.id !== task.id); save(); render(); });
    item.append(label, remove); list.append(item);
  }
  document.querySelector("#empty").hidden = visible.length > 0;
  document.querySelector("#summary").textContent = `${tasks.filter(t => !t.done).length} active · ${tasks.filter(t => t.done).length} completed`;
  for (const button of document.querySelectorAll("[data-filter]")) button.setAttribute("aria-pressed", String(button.dataset.filter === filter));
}
document.querySelector("#task-form").addEventListener("submit", event => {
  event.preventDefault(); const text = input.value.trim(); if (!text) return;
  tasks.push({id: crypto.randomUUID(), text, done: false}); input.value = ""; save(); render(); input.focus();
});
for (const button of document.querySelectorAll("[data-filter]")) button.addEventListener("click", () => { filter = button.dataset.filter; render(); });
render();
