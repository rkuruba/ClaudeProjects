async function loadConfig() {
  const res = await fetch('/config.json');
  return res.json();
}

async function loadUsers() {
  const res = await fetch('/api/users');
  const data = await res.json();
  document.getElementById('users').innerHTML = data.users
    .map((u) => `<li>#${u.id} ${u.name}</li>`)
    .join('');
  document.getElementById('meta').textContent =
    `served by ${data.node} | data source: ${data.source}`;
}

async function submitUser(event) {
  event.preventDefault();
  const input = document.getElementById('name');
  const res = await fetch('/api/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: input.value }),
  });
  const data = await res.json();
  input.value = '';
  document.getElementById('meta').textContent =
    `write handled by ${data.node} - refresh the list to watch replication lag`;
}

document.getElementById('signup').addEventListener('submit', submitUser);
loadConfig().then((cfg) => {
  document.getElementById('cdn-note').textContent = `static assets served by ${cfg.cdnUrl}`;
});
loadUsers();
