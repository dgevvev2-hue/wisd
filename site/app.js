/* wisd panel JS app */

const API_BASE = location.protocol === 'file:' ? 'http://127.0.0.1:8080' : '';

const state = {
    nodes: [],
    subs: [],
    vpn: null,
    selectedId: null,
    mode: 'direct',
    server: null,
    subAddMode: 'url',
};

const $ = (sel, root=document) => root.querySelector(sel);
const $$ = (sel, root=document) => Array.from(root.querySelectorAll(sel));

function api(path, opts={}) {
    return fetch(`${API_BASE}/cgi-bin/${path}`, opts).then(async r => {
        const ct = r.headers.get('content-type') || '';
        const body = ct.includes('application/json') ? await r.json() : await r.text();
        if (!r.ok) throw new Error((body && body.message) || `HTTP ${r.status}`);
        return body;
    });
}

function toast(msg, isErr=false, ms=2400) {
    const t = $('#toast');
    t.textContent = msg;
    t.classList.toggle('err', !!isErr);
    t.classList.add('show');
    clearTimeout(toast._h);
    toast._h = setTimeout(() => t.classList.remove('show'), ms);
}

function fmtElapsed(s) {
    s = Math.max(0, parseInt(s || 0, 10));
    const h = String(Math.floor(s / 3600)).padStart(2, '0');
    const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    return `${h}:${m}:${ss}`;
}

function fmtAge(epochSec) {
    if (!epochSec) return '—';
    const d = Math.floor(Date.now() / 1000 - epochSec);
    if (d < 60) return d + 's';
    if (d < 3600) return Math.floor(d/60) + 'm';
    if (d < 86400) return Math.floor(d/3600) + 'h';
    return Math.floor(d/86400) + 'd';
}

function fmtBytes(n) {
    n = Number(n) || 0;
    const u = ['B','KiB','MiB','GiB','TiB'];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function flagFromName(name) {
    if (!name) return '';
    const m = name.match(/^([\u{1F1E6}-\u{1F1FF}]{2})/u);
    if (!m) return '';
    const codes = [...m[1]].map(c => c.codePointAt(0) - 0x1F1E6 + 0x61);
    if (codes.length !== 2) return '';
    return `assets/flags/${String.fromCharCode(codes[0])}${String.fromCharCode(codes[1])}.svg`;
}

/* ---------- tab switching ---------- */
$$('.tab').forEach(t => t.addEventListener('click', () => {
    $$('.tab').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    const page = t.dataset.page;
    $$('.page').forEach(p => p.classList.toggle('active', p.id === page));
    if (page === 'vpsPage') loadVps();
    if (page === 'systemPage') loadSystem();
    if (page === 'rulesPage') loadRules();
}));

/* ---------- theme ---------- */
$('#themeBtn').addEventListener('click', () => {
    const root = document.documentElement;
    const cur = root.getAttribute('data-theme') || 'dark';
    const next = cur === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('wisd-theme', next); } catch (_) {}
});
(() => {
    try {
        const t = localStorage.getItem('wisd-theme');
        if (t) document.documentElement.setAttribute('data-theme', t);
    } catch (_) {}
})();

/* ---------- reload ---------- */
$('#reloadBtn').addEventListener('click', () => refreshAll());

/* ---------- VPN status ---------- */
async function refreshStatus() {
    try {
        const r = await api('vpn.cgi?action=status');
        state.vpn = r;
        state.mode = r.mode;
        state.selectedId = r.selectedId ? Number(r.selectedId) : null;
        renderStatus();
    } catch (e) {
        toast('Ошибка: ' + e.message, true);
    }
}

function renderStatus() {
    const v = state.vpn || {};
    $('#timer').textContent = fmtElapsed(v.elapsed);
    const on = !!v.enabled;
    $('#powerBtn').classList.toggle('off', !on);
    $('#powerBtn').querySelector('.circle').textContent = on ? 'ON' : 'ON';
    $('#statusDot').classList.toggle('on', on);
    $('#statusText').textContent = on ? (v.mode === 'tunnel' ? 'В туннеле' : 'Direct (VPS-IP)') : 'Выключен';
    $('#statusSub').textContent = v.running ? `xray pid ` : '';

    $('#modeDirect').classList.toggle('active', state.mode === 'direct');
    $('#modeTunnel').classList.toggle('active', state.mode === 'tunnel');

    if (state.mode === 'tunnel' && v.selectedName) {
        $('#currentName').textContent = v.selectedName;
        $('#currentMeta').textContent = `${v.selectedHost || ''} · через VLESS`;
    } else {
        $('#currentName').textContent = 'Direct';
        $('#currentMeta').textContent = 'Трафик выходит с IP самого VPS';
    }

    // update server card highlight
    $$('.server').forEach(el => {
        const id = el.dataset.id;
        el.classList.toggle('active',
            (state.mode === 'tunnel' && Number(id) === Number(state.selectedId)) ||
            (state.mode === 'direct' && id === '__direct__'));
    });
}

/* ---------- power & mode ---------- */
$('#powerBtn').addEventListener('click', async () => {
    const v = state.vpn || {};
    try {
        if (v.enabled) {
            await api('vpn.cgi?action=down');
            toast('Туннель выключен');
        } else {
            if (state.mode === 'tunnel' && state.selectedId != null) {
                await api(`vpn.cgi?action=up&mode=tunnel&id=${state.selectedId}`);
            } else {
                await api('vpn.cgi?action=up&mode=direct');
            }
            toast('Включено');
        }
        await refreshStatus();
    } catch (e) {
        toast('Не удалось: ' + e.message, true);
    }
});

$('#modeDirect').addEventListener('click', async () => {
    state.mode = 'direct';
    state.selectedId = null;
    try {
        await api('vpn.cgi?action=up&mode=direct');
        toast('Direct');
    } catch (e) {
        toast(e.message, true);
    }
    await refreshStatus();
});

$('#modeTunnel').addEventListener('click', () => {
    state.mode = 'tunnel';
    renderStatus();
    if (!state.nodes.length) toast('Сначала добавь подписку с узлами', true);
});

$('#restartBtn').addEventListener('click', async () => {
    try {
        await api('vpn.cgi?action=restart');
        toast('Перезапущен');
        await refreshStatus();
    } catch (e) { toast(e.message, true); }
});

$('#clearLogBtn').addEventListener('click', async () => {
    try {
        await api('vpn.cgi?action=clearlogs');
        toast('Логи очищены');
        refreshLog();
    } catch (e) { toast(e.message, true); }
});

/* ---------- log tail ---------- */
async function refreshLog() {
    try {
        const r = await api('traffic.cgi?action=log&lines=20');
        $('#log').textContent = (r.log || '').trim() || '(пусто)';
    } catch (_) {
        $('#log').textContent = '(нет данных)';
    }
}

/* ---------- subscriptions / nodes ---------- */
async function refreshSubs() {
    try {
        const r = await api('subscription.cgi?action=list');
        state.subs = r.subscriptions || [];
        state.nodes = r.nodes || [];
        renderSubs();
        renderServers();
    } catch (e) {
        toast('Подписки: ' + e.message, true);
    }
}

function renderSubs() {
    const box = $('#subList');
    if (!state.subs.length) {
        box.innerHTML = '<div class="empty">Пока нет ни одной подписки.</div>';
        return;
    }
    box.innerHTML = state.subs.map(s => `
        <div class="subItem">
            <div>
                <div class="nm">${escapeHtml(s.name)}</div>
                ${s.url ? `<div class="url">${escapeHtml(s.url)}</div>` : '<div class="url">(ручная вставка)</div>'}
                <div class="meta">${s.count} серверов · обновлено ${fmtAge(s.fetchedAt)} назад</div>
            </div>
            <div class="subBtns">
                ${s.url ? `<button class="btn" data-fetch="${s.id}" title="Обновить">↻</button>` : ''}
                <button class="btn bad" data-del="${s.id}" title="Удалить">×</button>
            </div>
        </div>
    `).join('');
    box.querySelectorAll('[data-fetch]').forEach(b => b.addEventListener('click', async () => {
        b.disabled = true;
        try {
            const r = await api(`subscription.cgi?action=fetch&id=${b.dataset.fetch}`);
            toast(`Обновлено: ${r.count} узлов`);
            await refreshSubs();
        } catch (e) { toast(e.message, true); }
        b.disabled = false;
    }));
    box.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => {
        if (!confirm('Удалить подписку?')) return;
        try {
            await api(`subscription.cgi?action=remove&id=${b.dataset.del}`);
            toast('Удалено');
            await refreshSubs();
        } catch (e) { toast(e.message, true); }
    }));
}

$$('.subAddTabs .tt').forEach(t => t.addEventListener('click', () => {
    $$('.subAddTabs .tt').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    state.subAddMode = t.dataset.add;
    $('#subAddUrl').style.display = state.subAddMode === 'url' ? '' : 'none';
    $('#subAddPaste').style.display = state.subAddMode === 'paste' ? '' : 'none';
}));

$('#subAddBtn').addEventListener('click', async () => {
    const name = $('#subName').value.trim() || 'Subscription';
    try {
        if (state.subAddMode === 'url') {
            const url = $('#subUrl').value.trim();
            if (!url) return toast('Введите URL', true);
            await api(`subscription.cgi?action=add&name=${encodeURIComponent(name)}&url=${encodeURIComponent(url)}`);
        } else {
            const body = $('#subPaste').value;
            if (!body.trim()) return toast('Вставьте VLESS-строки', true);
            await api(`subscription.cgi?action=add&name=${encodeURIComponent(name)}`, {
                method: 'POST', body
            });
        }
        $('#subName').value = '';
        $('#subUrl').value = '';
        $('#subPaste').value = '';
        toast('Подписка добавлена');
        await refreshSubs();
    } catch (e) {
        toast('Ошибка: ' + e.message, true);
    }
});

/* ---------- servers list ---------- */
function renderServers() {
    const box = $('#serversBox');
    const q = ($('#search').value || '').toLowerCase().trim();
    const items = [];

    // Always include "Direct" pseudo-server
    items.push(`
        <div class="server directCard" data-id="__direct__">
            <div style="width:28px;height:28px;border-radius:8px;background:linear-gradient(135deg,var(--accent),var(--accent-2))"></div>
            <div class="info">
                <div class="nm">Direct (этот VPS)</div>
                <div class="mt">Выход с IP-адреса VPS · без upstream</div>
            </div>
            <div class="right-meta">Default</div>
        </div>
    `);
    state.nodes
        .filter(n => !q || (n.name || '').toLowerCase().includes(q) || (n.host || '').includes(q))
        .forEach(n => {
            const flag = flagFromName(n.name);
            const flagHtml = flag
                ? `<img class="flag" src="${flag}" onerror="this.style.display='none'">`
                : `<div class="flag" style="background:var(--bg-elev)"></div>`;
            items.push(`
                <div class="server" data-id="${n.id}">
                    ${flagHtml}
                    <div class="info">
                        <div class="nm">${escapeHtml(n.name || n.host)}</div>
                        <div class="mt">${escapeHtml(n.host)}:${n.port || 443} · ${escapeHtml(n.type || 'tcp')}/${escapeHtml(n.security || 'none')}</div>
                    </div>
                    <div class="right-meta">${escapeHtml((n.security || '').toUpperCase())}</div>
                </div>
            `);
        });
    box.innerHTML = items.join('');
    box.querySelectorAll('.server').forEach(el => {
        el.addEventListener('click', () => selectNode(el.dataset.id));
    });
    renderStatus();
}

async function selectNode(id) {
    if (id === '__direct__') {
        state.mode = 'direct';
        state.selectedId = null;
        try { await api('vpn.cgi?action=up&mode=direct'); toast('Direct'); }
        catch (e) { toast(e.message, true); }
        await refreshStatus();
        return;
    }
    state.mode = 'tunnel';
    state.selectedId = Number(id);
    try {
        await api(`vpn.cgi?action=up&mode=tunnel&id=${id}`);
        toast('Подключено');
    } catch (e) { toast(e.message, true); }
    await refreshStatus();
}

$('#search').addEventListener('input', renderServers);

/* ---------- this VPS / server info ---------- */
async function loadVps() {
    const box = $('#vpsBox');
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
        const r = await api('server.cgi');
        state.server = r;
        if (!r.ok) {
            box.innerHTML = `<div class="empty">${escapeHtml(r.message || 'не настроен')}</div>`;
            return;
        }
        const p = r.proxy || {};
        box.innerHTML = `
            <h3 style="margin:0 0 10px">VLESS-Reality (туннель)</h3>
            <div class="row"><span>Адрес</span><b>${escapeHtml(r.host)}:${r.port}</b></div>
            <div class="row"><span>Протокол</span><b>VLESS · Reality</b></div>
            <div class="row"><span>UUID</span><b class="mono">${escapeHtml(r.uuid)}</b></div>
            <div class="row"><span>Public key</span><b class="mono">${escapeHtml(r.publicKey)}</b></div>
            <div class="row"><span>Short ID</span><b class="mono">${escapeHtml(r.shortId)}</b></div>
            <div class="row"><span>SNI</span><b>${escapeHtml(r.serverName)}</b></div>
            <div class="row"><span>Flow</span><b>${escapeHtml(r.flow)}</b></div>
            <div class="url" id="vlessUrl">${escapeHtml(r.url)}</div>
            <div class="row" style="justify-content:flex-end;gap:8px">
                <button id="copyUrl" class="btn">Копировать VLESS</button>
            </div>

            <hr style="border:none;border-top:1px solid var(--border);margin:18px 0">

            <h3 style="margin:0 0 10px">SOCKS5 / HTTP прокси</h3>
            <div class="row"><span>SOCKS5</span><b class="mono">${escapeHtml(r.host)}:${p.socksPort || ''}</b></div>
            <div class="row"><span>HTTP</span><b class="mono">${escapeHtml(r.host)}:${p.httpPort || ''}</b></div>
            <div class="row"><span>Логин</span><b class="mono">${escapeHtml(p.user || '')}</b></div>
            <div class="row"><span>Пароль</span><b class="mono">${escapeHtml(p.pass || '')}</b></div>
            <div class="url" id="socksUrl">${escapeHtml(p.socksUrl || '')}</div>
            <div class="row" style="justify-content:flex-end;gap:8px">
                <button id="copySocks" class="btn">SOCKS5 URL</button>
                <button id="copyHttp" class="btn">HTTP URL</button>
                <button id="copyUser" class="btn">Логин</button>
                <button id="copyPass" class="btn">Пароль</button>
            </div>
            <div class="empty" style="margin-top:8px;font-size:12px">
                В отличие от VLESS, обычный SOCKS5/HTTP не маскируется — провайдер видит, что это прокси.
                Используй для отдельных приложений (браузер, qBittorrent, curl, Python requests и т.д.).
            </div>
        `;
        const copy = (txt) => navigator.clipboard.writeText(txt).then(() => toast('Скопировано'));
        $('#copyUrl').addEventListener('click', () => copy(r.url));
        $('#copySocks').addEventListener('click', () => copy(p.socksUrl || ''));
        $('#copyHttp').addEventListener('click', () => copy(p.httpUrl || ''));
        $('#copyUser').addEventListener('click', () => copy(p.user || ''));
        $('#copyPass').addEventListener('click', () => copy(p.pass || ''));
    } catch (e) {
        box.innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`;
    }
}

/* ---------- system info ---------- */
async function loadSystem() {
    const box = $('#sysBox');
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
        const r = await api('info.cgi');
        const t = await api('traffic.cgi?action=stats');
        const memTotal = (r.memTotalKb * 1024) || 0;
        const memAvail = (r.memAvailKb * 1024) || 0;
        const memUsed = memTotal - memAvail;
        const disk = (r.disk || '').split(',');
        box.innerHTML = `
            <div class="row"><span>Host</span><b>${escapeHtml(r.host)}</b></div>
            <div class="row"><span>OS</span><b>${escapeHtml(r.os || '')}</b></div>
            <div class="row"><span>Kernel</span><b class="mono">${escapeHtml(r.kernel)}</b></div>
            <div class="row"><span>Public IP</span><b class="mono">${escapeHtml(r.ip4)}</b></div>
            <div class="row"><span>Uptime</span><b>${fmtElapsed(r.uptime)}</b></div>
            <div class="row"><span>Load avg</span><b class="mono">${escapeHtml(r.load)}</b></div>
            <div class="row"><span>RAM</span><b>${fmtBytes(memUsed)} / ${fmtBytes(memTotal)}</b></div>
            <div class="row"><span>Disk</span><b>${disk[1] ? fmtBytes(Number(disk[1]) * 1024) : '—'} / ${disk[0] ? fmtBytes(Number(disk[0]) * 1024) : '—'}</b></div>
            <hr>
            <div class="row"><span>Xray</span><b>${r.xrayRunning ? 'running (pid '+escapeHtml(r.xrayPid)+')' : 'stopped'}</b></div>
            <div class="row"><span>Активных соединений</span><b>${t.connections || 0}</b></div>
        `;
    } catch (e) {
        box.innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`;
    }
}

/* ---------- rules ---------- */
async function loadRules() {
    try {
        const r = await api('rules.cgi?action=get');
        $('#rulesDirect').value = (r.direct || []).join('\n');
        $('#rulesTunnel').value = (r.tunnel || []).join('\n');
    } catch (e) { toast(e.message, true); }
}
$('#rulesSaveBtn').addEventListener('click', async () => {
    const direct = $('#rulesDirect').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    const tunnel = $('#rulesTunnel').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    try {
        await api('rules.cgi?action=set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ direct, tunnel })
        });
        toast('Сохранено');
    } catch (e) { toast(e.message, true); }
});

/* ---------- helpers ---------- */
function escapeHtml(s) {
    return String(s == null ? '' : s)
        .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
        .replaceAll('"','&quot;').replaceAll("'", '&#39;');
}

/* ---------- bootstrap ---------- */
async function refreshAll() {
    await Promise.all([refreshStatus(), refreshSubs(), refreshLog()]);
}
refreshAll();
setInterval(refreshStatus, 5000);
setInterval(refreshLog, 10000);
