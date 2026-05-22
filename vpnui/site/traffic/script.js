const API_BASE = location.protocol === 'file:' ? 'http://192.168.0.1:8084' : '';
const $ = (id) => document.getElementById(id);

let rawData = { devices: [], events: [] };
let sites = [];
let cleared = false;
let loading = true;
let filters = { query: '', category: 'Все', status: 'Все', sort: 'visits' };

const categoryRules = [
  ['Видео', ['youtube', 'youtu.be', 'googlevideo', 'ytimg', 'kinopoisk', 'kion', 'rutube', 'twitch']],
  ['Поиск', ['google.', 'yandex.', 'ya.ru', 'bing.', 'duckduckgo']],
  ['Соцсети', ['instagram', 'facebook', 'vk.com', 'twitter', 'x.com', 'tiktok', 'threads']],
  ['Работа', ['mail.', 'calendar', 'zoom', 'slack', 'notion', 'figma', 'office', 'teams']],
  ['Разработка', ['github', 'stackoverflow', 'npmjs', 'docker', 'openai', 'chatgpt', 'codex', 'gitlab']],
  ['Новости', ['news', 'rbc', 'lenta', 'ria', 'meduza', 'bbc', 'cnn']],
  ['Реклама', ['tracker', 'doubleclick', 'ads.', 'analytics', 'metrika', 'adservice']]
];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (m) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[m]));
}

function bytes(value) {
  let n = Number(value || 0);
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${i === 0 || n >= 10 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`;
}

function showToast(message) {
  const item = document.createElement('div');
  item.className = 'toast-item';
  item.textContent = message;
  $('toast').appendChild(item);
  setTimeout(() => item.remove(), 2800);
}

async function getJson(path) {
  const response = await fetch(API_BASE + path, { cache: 'no-store' });
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(text.slice(0, 160) || response.statusText);
  }
}

function categoryFor(domain) {
  const d = String(domain || '').toLowerCase();
  const hit = categoryRules.find(([, keys]) => keys.some((key) => d.includes(key)));
  return hit ? hit[0] : 'Неизвестно';
}

function statusFor(domain, visits) {
  const d = String(domain || '').toLowerCase();
  if (d.includes('malware') || d.includes('phishing')) return 'Заблокирован';
  if (d.includes('tracker') || d.includes('ads') || d.includes('doubleclick') || visits > 80) return 'Подозрительный';
  return 'Разрешён';
}

function hostFromEvent(event) {
  return String(event.domain || event.url || '').replace(/^https?:\/\//, '').replace(/^tcp:/, '').replace(/^udp:/, '').split('/')[0].replace(/:\d+$/, '').toLowerCase();
}

function buildSites() {
  const grouped = new Map();
  (rawData.events || []).forEach((event) => {
    const domain = hostFromEvent(event);
    if (!domain) return;
    const row = grouped.get(domain) || {
      domain,
      category: categoryFor(domain),
      visits: 0,
      trafficValue: 0,
      lastVisit: event.time || '',
      status: 'Разрешён'
    };
    row.visits += 1;
    row.lastVisit = event.time || row.lastVisit;
    row.trafficValue += Math.max(1, Math.round((event.bytes || 0) / 1024 / 1024));
    grouped.set(domain, row);
  });

  sites = Array.from(grouped.values()).map((site) => {
    site.status = statusFor(site.domain, site.visits);
    site.trafficValue = site.trafficValue || Math.max(1, Math.round(site.visits * 2.5));
    site.traffic = `${site.trafficValue} MB`;
    return site;
  });
}

function deviceTotals() {
  return (rawData.devices || []).reduce((acc, device) => {
    acc.rx += Number(device.rx || 0);
    acc.tx += Number(device.tx || 0);
    acc.speed += Number(device.rxps || 0) + Number(device.txps || 0);
    return acc;
  }, { rx: 0, tx: 0, speed: 0 });
}

function filteredSites() {
  const query = filters.query.toLowerCase();
  let rows = sites.filter((site) => {
    const byQuery = !query || site.domain.toLowerCase().includes(query);
    const byCategory = filters.category === 'Все' || site.category === filters.category;
    const byStatus = filters.status === 'Все' || site.status === filters.status;
    return byQuery && byCategory && byStatus;
  });
  rows = rows.sort((a, b) => {
    if (filters.sort === 'traffic') return b.trafficValue - a.trafficValue;
    if (filters.sort === 'lastVisit') return String(b.lastVisit).localeCompare(String(a.lastVisit));
    return b.visits - a.visits;
  });
  return rows;
}

function renderSkeleton() {
  $('statsGrid').innerHTML = Array.from({ length: 4 }).map(() => '<div class="stat-card skeleton" style="height:138px"></div>').join('');
  $('sitesTable').innerHTML = '<div class="empty-state"><strong>Загрузка</strong><span>Получаем реальные данные с роутера.</span></div>';
  $('topSites').innerHTML = Array.from({ length: 5 }).map(() => '<div class="site-row skeleton" style="height:70px"></div>').join('');
  $('liveTraffic').innerHTML = Array.from({ length: 4 }).map(() => '<div class="live-row skeleton" style="height:64px"></div>').join('');
}

function renderStats() {
  const totals = deviceTotals();
  const blocked = sites.filter((site) => site.status === 'Заблокирован').length;
  const stats = [
    { title: 'Посещено сайтов', value: sites.length, foot: 'по доступной истории', trend: sites.length ? '+ live' : '0', icon: '○' },
    { title: 'Общий трафик', value: bytes(totals.rx + totals.tx), foot: 'входящий и исходящий', trend: bytes(totals.speed) + '/s', icon: '↕' },
    { title: 'Активное время', value: activityTime(), foot: 'сегодня', trend: 'online', icon: '◷' },
    { title: 'Заблокировано', value: blocked, foot: 'подозрительных запросов', trend: blocked ? 'check' : 'clean', icon: '◇' }
  ];
  $('statsGrid').innerHTML = stats.map((card, index) => `
    <article class="stat-card" style="animation-delay:${index * 45}ms">
      <div class="stat-head">
        <span class="stat-title">${escapeHtml(card.title)}</span>
        <span class="stat-icon">${card.icon}</span>
      </div>
      <div class="stat-value">${escapeHtml(card.value)}</div>
      <div class="stat-foot"><span class="trend">${escapeHtml(card.trend)}</span>${escapeHtml(card.foot)}</div>
    </article>
  `).join('');
}

function activityTime() {
  const count = (rawData.events || []).length;
  if (!count) return '0 мин';
  const minutes = Math.min(24 * 60, Math.max(1, Math.round(count * 3)));
  if (minutes < 60) return `${minutes} мин`;
  return `${Math.floor(minutes / 60)} ч ${minutes % 60} мин`;
}

function renderChart() {
  const svg = $('activityChart');
  const empty = $('chartEmpty');
  const events = rawData.events || [];
  if (!events.length || cleared) {
    svg.innerHTML = '';
    empty.style.display = 'grid';
    return;
  }
  empty.style.display = 'none';
  const buckets = Array.from({ length: 12 }, (_, index) => ({ label: `${index * 2}:00`, visits: 0, traffic: 0 }));
  events.forEach((event, index) => {
    const bucket = buckets[index % buckets.length];
    bucket.visits += 1;
    bucket.traffic += Math.max(1, Number(event.bytes || 0) / 1024 / 1024);
  });
  const width = 760, height = 280, pad = 34;
  const maxVisits = Math.max(1, ...buckets.map((b) => b.visits));
  const maxTraffic = Math.max(1, ...buckets.map((b) => b.traffic));
  const x = (i) => pad + (i * (width - pad * 2)) / (buckets.length - 1);
  const yVisits = (v) => height - pad - (v / maxVisits) * (height - pad * 2);
  const yTraffic = (v) => height - pad - (v / maxTraffic) * (height - pad * 2);
  const line = (key, yFn) => buckets.map((b, i) => `${i ? 'L' : 'M'} ${x(i).toFixed(1)} ${yFn(b[key]).toFixed(1)}`).join(' ');
  const area = (key, yFn) => `${line(key, yFn)} L ${width - pad} ${height - pad} L ${pad} ${height - pad} Z`;
  svg.innerHTML = `
    <defs>
      <linearGradient id="visitFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#2563eb"/><stop offset="1" stop-color="#2563eb" stop-opacity="0"/></linearGradient>
      <linearGradient id="trafficFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#10b981"/><stop offset="1" stop-color="#10b981" stop-opacity="0"/></linearGradient>
    </defs>
    ${[0, 1, 2, 3].map((i) => `<line class="chart-grid" x1="${pad}" y1="${pad + i * 62}" x2="${width - pad}" y2="${pad + i * 62}"></line>`).join('')}
    <path class="chart-area" fill="url(#visitFill)" d="${area('visits', yVisits)}"></path>
    <path class="chart-area" fill="url(#trafficFill)" d="${area('traffic', yTraffic)}"></path>
    <path class="chart-line" stroke="#2563eb" d="${line('visits', yVisits)}"></path>
    <path class="chart-line" stroke="#10b981" d="${line('traffic', yTraffic)}"></path>
    ${buckets.map((b, i) => `<text class="chart-label" x="${x(i)}" y="${height - 8}" text-anchor="middle">${b.label}</text>`).join('')}
    ${buckets.map((b, i) => `<circle class="chart-point" cx="${x(i)}" cy="${yVisits(b.visits)}" r="4" stroke="#2563eb"><title>${b.label}: ${b.visits} посещений</title></circle>`).join('')}
  `;
}

function renderTopSites() {
  const rows = sites.slice().sort((a, b) => b.visits - a.visits).slice(0, 6);
  if (!rows.length) {
    $('topSites').innerHTML = emptyState('История пуста', 'Новые посещённые сайты появятся здесь после начала мониторинга.');
    return;
  }
  const max = Math.max(1, ...rows.map((row) => row.visits));
  $('topSites').innerHTML = rows.map((row) => `
    <div class="site-row">
      <div class="favicon">${escapeHtml(row.domain[0]?.toUpperCase() || '?')}</div>
      <div>
        <div class="site-name">${escapeHtml(row.domain)}</div>
        <div class="site-meta">${escapeHtml(row.category)} · Последний визит: ${escapeHtml(row.lastVisit || 'сейчас')}</div>
      </div>
      <div class="site-value">${row.visits} посещений<br>${escapeHtml(row.traffic)}</div>
      <div class="progress"><span style="width:${Math.round(row.visits / max * 100)}%"></span></div>
    </div>
  `).join('');
}

function badgeClass(status) {
  if (status === 'Заблокирован') return 'bad';
  if (status === 'Подозрительный') return 'warn';
  return 'ok';
}

function renderTable() {
  const rows = filteredSites();
  if (!sites.length) {
    $('sitesTable').innerHTML = emptyState('История пуста', 'Новые посещённые сайты появятся здесь после начала мониторинга.');
    return;
  }
  if (!rows.length) {
    $('sitesTable').innerHTML = emptyState('Ничего не найдено', 'Попробуйте изменить поиск или фильтры.');
    return;
  }
  $('sitesTable').innerHTML = `
    <div class="table-row head"><div>Сайт</div><div>Категория</div><div>Посещения</div><div>Трафик</div><div>Последний визит</div><div>Статус</div></div>
    ${rows.map((row, index) => `
      <div class="table-row" style="animation-delay:${index * 22}ms">
        <div class="domain-cell"><span class="favicon">${escapeHtml(row.domain[0]?.toUpperCase() || '?')}</span><span class="domain-title">${escapeHtml(row.domain)}</span></div>
        <div>${escapeHtml(row.category)}</div>
        <div>${row.visits}</div>
        <div>${escapeHtml(row.traffic)}</div>
        <div>${escapeHtml(row.lastVisit || 'сейчас')}</div>
        <div><span class="badge ${badgeClass(row.status)}">${escapeHtml(row.status)}</span></div>
      </div>
    `).join('')}
  `;
}

function renderLiveTraffic() {
  const events = (rawData.events || []).slice(-8).reverse();
  if (!events.length) {
    $('liveTraffic').innerHTML = emptyState('Нет событий', 'Live traffic появится после активности клиентов.');
    return;
  }
  $('liveTraffic').innerHTML = events.map((event, index) => {
    const domain = hostFromEvent(event) || 'unknown';
    const amount = event.bytes ? bytes(event.bytes) : '';
    return `
      <div class="live-row" style="animation-delay:${index * 40}ms">
        <div class="favicon">${escapeHtml(domain[0]?.toUpperCase() || '?')}</div>
        <div>
          <div class="site-name">${escapeHtml(event.url || domain)}</div>
          <div class="live-meta">${escapeHtml(event.src || 'router')} · ${amount || 'домен'} · ${escapeHtml(event.time || 'только что')}</div>
        </div>
        <span class="pulse"></span>
      </div>
    `;
  }).join('');
}

function emptyState(title, text) {
  return `
    <div class="empty-state">
      <div class="empty-icon">○</div>
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(text)}</span>
    </div>
  `;
}

function renderAll() {
  buildSites();
  renderStats();
  renderChart();
  renderTopSites();
  renderTable();
  renderLiveTraffic();
}

async function loadTraffic(silent = false) {
  if (!silent) renderSkeleton();
  loading = true;
  try {
    rawData = await getJson('/cgi-bin/traffic.cgi?action=status');
    cleared = false;
    renderAll();
    if (silent) return;
    showToast('Данные обновлены');
  } catch (error) {
    $('sitesTable').innerHTML = emptyState('Ошибка загрузки', error.message);
    showToast('Не удалось загрузить данные');
  } finally {
    loading = false;
  }
}

async function clearHistory() {
  $('confirmClear').disabled = true;
  try {
    await getJson('/cgi-bin/traffic.cgi?action=clear');
    rawData = { devices: rawData.devices || [], events: [] };
    sites = [];
    cleared = true;
    closeModal();
    renderAll();
    showToast('История очищена');
  } catch (error) {
    showToast('Ошибка очистки');
  } finally {
    $('confirmClear').disabled = false;
  }
}

function exportReport() {
  const payload = JSON.stringify({ exportedAt: new Date().toISOString(), sites, devices: rawData.devices || [] }, null, 2);
  const blob = new Blob([payload], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'traffic-report.json';
  link.click();
  URL.revokeObjectURL(url);
  showToast('Отчёт экспортирован');
}

function openModal() {
  $('clearModal').classList.add('open');
  $('clearModal').setAttribute('aria-hidden', 'false');
}

function closeModal() {
  $('clearModal').classList.remove('open');
  $('clearModal').setAttribute('aria-hidden', 'true');
}

$('searchInput').addEventListener('input', (event) => {
  filters.query = event.target.value;
  renderTable();
});
$('categoryFilter').addEventListener('change', (event) => {
  filters.category = event.target.value;
  renderTable();
});
$('statusFilter').addEventListener('change', (event) => {
  filters.status = event.target.value;
  renderTable();
});
$('sortSelect').addEventListener('change', (event) => {
  filters.sort = event.target.value;
  renderTable();
});
$('refreshButton').addEventListener('click', async () => {
  $('refreshButton').disabled = true;
  await new Promise((resolve) => setTimeout(resolve, 1000));
  await loadTraffic(true);
  $('refreshButton').disabled = false;
  showToast('Данные обновлены');
});
$('exportButton').addEventListener('click', exportReport);
$('clearButton').addEventListener('click', openModal);
$('cancelClear').addEventListener('click', closeModal);
$('confirmClear').addEventListener('click', clearHistory);
$('clearModal').addEventListener('click', (event) => {
  if (event.target.id === 'clearModal') closeModal();
});

loadTraffic();
setInterval(() => {
  if (!loading && !cleared) loadTraffic(true);
}, 5000);
