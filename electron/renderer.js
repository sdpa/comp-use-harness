const tasks = [
  { id: 't1', label: 'Ensure iTunes is open and focused', type: 'app_launcher', status: 'success' },
  { id: 't2', label: 'Start music playback', type: 'ui_navigator', status: 'success' },
  { id: 't3', label: 'Confirm playback is active', type: 'verifier', status: 'success' },
];

const list = document.getElementById('task-list');
const status = document.getElementById('status');

status.textContent = 'Running';

for (const task of tasks) {
  const item = document.createElement('li');
  item.innerHTML = `
    <div>
      <strong>${task.id}</strong> — ${task.label}
    </div>
    <span class="task-tag ${task.status}">${task.type}</span>
  `;
  list.appendChild(item);
}

window.addEventListener('DOMContentLoaded', () => {
  const app = window.appInfo;
  status.textContent = `Ready (${app.version})`;
});
