'use strict';

let autoStarting = false;
let selectedDays = 14;
let data = null;
let ragStale = false;
let renderedWizardKey = null;
let chartAnimationFrame = 0;
let suppressAutoAccount = sessionStorage.getItem('tg-mcp-suppress-auto-account') === '1';
const reducedChartMotion = window.matchMedia
  ? window.matchMedia('(prefers-reduced-motion: reduce)')
  : {matches: false};
const $ = (id) => document.getElementById(id);
const q = (selector, root = document) => root.querySelector(selector);
const qa = (selector, root = document) => [...root.querySelectorAll(selector)];

function replaceIcons(root = document) {
  const icons = root.matches?.('i.ph') ? [root] : qa('i.ph', root);
  icons.forEach((icon) => {
    const name = [...icon.classList].find((value) => value.startsWith('ph-'));
    if (!name) return;
    const image = document.createElement('img');
    image.src = `/assets/icon-${name.slice(3)}.svg`;
    image.className = 'ui-icon';
    image.alt = '';
    image.setAttribute('aria-hidden', 'true');
    icon.replaceWith(image);
  });
}

replaceIcons();
new MutationObserver((records) => records.forEach((record) => record.addedNodes.forEach((node) => {
  if (node.nodeType === Node.ELEMENT_NODE) replaceIcons(node);
}))).observe(document.body, {childList: true, subtree: true});
const viewCopy = {
  overview: ['Обзор', 'Состояние сервиса, статистика и последние операции'],
  accounts: ['Аккаунты', 'Подключение и управление пользовательскими аккаунтами'],
  bots: ['Боты', 'Опциональные Telegram-боты для отправки сообщений'],
  activity: ['Активность', 'История операций и использование по аккаунтам'],
  rag: ['RAG', 'Фоновая загрузка истории и локальный семантический поиск'],
  access: ['Доступ MCP', 'Параметры подключения агентов'],
  settings: ['Настройки', 'Правила хранения и параметры экземпляра'],
};
const operationCopy = {
  get_status: ['Статус сервиса', 'read', 'ph-heartbeat'],
  list_accounts: ['Список аккаунтов', 'read', 'ph-users'],
  list_bots: ['Список ботов', 'read', 'ph-robot'],
  get_capabilities: ['Возможности', 'read', 'ph-list'],
  list_chats: ['Список чатов', 'read', 'ph-chats-circle'],
  find_chats: ['Поиск чатов', 'search', 'ph-magnifying-glass'],
  get_unread_inbox: ['Непрочитанные', 'read', 'ph-chats-circle'],
  get_inbox_context: ['Контекст входящих', 'read', 'ph-chats-circle'],
  list_folders: ['Папки', 'read', 'ph-list'],
  get_folder_messages: ['Сообщения папки', 'search', 'ph-magnifying-glass'],
  get_chat_history: ['Чтение истории', 'read', 'ph-file-text'],
  find_messages: ['Поиск в архиве и Telegram', 'search', 'ph-magnifying-glass'],
  search_messages: ['Поиск', 'search', 'ph-magnifying-glass'],
  search_all_messages: ['Глобальный поиск', 'search', 'ph-magnifying-glass'],
  get_message: ['Сообщение', 'read', 'ph-file-text'],
  get_message_context: ['Контекст сообщения', 'read', 'ph-file-text'],
  get_reply_thread: ['Ветка ответов', 'read', 'ph-file-text'],
  get_conversation_snapshot: ['Снимок диалога', 'read', 'ph-file-text'],
  resolve_peer: ['Поиск адресата', 'search', 'ph-magnifying-glass'],
  search_chat_content: ['Поиск контента', 'search', 'ph-magnifying-glass'],
  poll_updates: ['Новые события', 'read', 'ph-arrow-right'],
  list_attachments: ['Поиск вложений', 'search', 'ph-file-text'],
  get_chat_info: ['Сведения о чате', 'read', 'ph-user'],
  resolve_message_link: ['Разбор ссылки', 'search', 'ph-link'],
  list_topics: ['Темы', 'read', 'ph-list'],
  get_recent_mentions: ['Упоминания', 'read', 'ph-user'],
  download_attachment: ['Загрузка вложения', 'read', 'ph-arrow-right'],
  download_attachment_chunk: ['Часть вложения', 'read', 'ph-arrow-right'],
  send_as_user: ['Отправка', 'send', 'ph-paper-plane-tilt'],
  edit_own_message: ['Изменение сообщения', 'send', 'ph-file-text'],
  schedule_message: ['Планирование', 'send', 'ph-paper-plane-tilt'],
  list_scheduled_messages: ['Запланированные', 'read', 'ph-list'],
  cancel_scheduled_message: ['Отмена отправки', 'send', 'ph-circle'],
  send_as_bot: ['Отправка ботом', 'send', 'ph-paper-plane-tilt'],
  send_attachment: ['Отправка вложения', 'send', 'ph-paper-plane-tilt'],
  forward_messages: ['Пересылка', 'send', 'ph-paper-plane-tilt'],
  mark_chat_read: ['Прочитано', 'send', 'ph-check'],
  react_to_message: ['Реакция', 'send', 'ph-circle'],
  create_draft: ['Создание черновика', 'send', 'ph-file-text'],
  list_drafts: ['Черновики', 'read', 'ph-list'],
  send_draft: ['Отправка черновика', 'send', 'ph-paper-plane-tilt'],
  delete_draft: ['Удаление черновика', 'send', 'ph-circle'],
  create_agent_token: ['Создание токена агента', 'send', 'ph-user'],
  list_agent_tokens: ['Токены агентов', 'read', 'ph-users'],
  revoke_agent_token: ['Отзыв токена агента', 'send', 'ph-circle'],
};

async function api(path, options = {}) {
  options.headers = {
    ...(options.body ? {'Content-Type': 'application/json'} : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(path, options);
  let body = {};
  try { body = await response.json(); } catch {}
  if (!response.ok) throw new Error(body.error?.message || body.error || `HTTP ${response.status}`);
  return body;
}

function showNotice(message, success = false) {
  const notice = $('notice');
  notice.textContent = message;
  notice.hidden = false;
  notice.style.borderColor = success ? '#275b45' : '';
  notice.style.background = success ? '#102d22' : '';
  notice.style.color = success ? '#75e9aa' : '';
  clearTimeout(showNotice.timer);
  showNotice.timer = setTimeout(() => { notice.hidden = true; }, 3500);
}

function navigate(view) {
  const actualPage = view === 'activity' ? 'overview' : view;
  qa('.view').forEach((page) => page.classList.toggle('active', page.dataset.page === actualPage));
  qa('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.view === view));
  const overview = q('[data-page="overview"]');
  overview.classList.toggle('activity-only', view === 'activity');
  $('pageTitle').textContent = viewCopy[view][0];
  $('pageSubtitle').textContent = viewCopy[view][1];
  history.replaceState(null, '', view === 'overview' ? location.pathname : `#${view}`);
  $('headerConnect').hidden = view !== 'accounts' || Boolean(data?.accounts?.some(a=>['connecting','waiting_qr','waiting_2fa','waiting_name'].includes(a.status)));
  requestAnimationFrame(drawRagQueue);
  closeSidebar();
  window.scrollTo({top: 0, behavior: 'smooth'});
  if (view === 'activity') setTimeout(() => q('.activity-panel', overview)?.scrollIntoView({block: 'start'}), 50);
  if (view === 'overview' || view === 'activity') startChartAnimation();
}

function openSidebar() {
  $('sidebar').classList.add('open');
  $('sidebarScrim').hidden = false;
  $('mobileMenu').setAttribute('aria-expanded', 'true');
}
function closeSidebar() {
  $('sidebar').classList.remove('open');
  $('sidebarScrim').hidden = true;
  $('mobileMenu').setAttribute('aria-expanded', 'false');
}

function formatNumber(value) { return new Intl.NumberFormat('ru-RU').format(value || 0); }
function formatDateTime(value) {
  const date = new Date(value);
  return new Intl.DateTimeFormat('ru-RU', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit'}).format(date).replace(',', ' ·');
}
function formatBucket(value, days) {
  const date = new Date(days === 1 ? value : `${value}T00:00:00Z`);
  if (days === 1) return new Intl.DateTimeFormat('ru-RU', {hour: '2-digit', minute: '2-digit'}).format(date);
  return new Intl.DateTimeFormat('ru-RU', days <= 7 ? {weekday: 'short'} : {day: 'numeric', month: 'short'}).format(date);
}
function identityName(id) {
  if (!id) return 'Сервис';
  const row = [...(data?.accounts || []), ...(data?.bots || [])].find((item) => (item.account_id || item.bot_id) === id);
  return row?.label || row?.username || id;
}
function identityHandle(row) { return row.username ? `@${row.username}` : (row.account_id || row.bot_id); }
function statusLabel(status) {
  return ({ready: 'Онлайн', disabled: 'Отключён', revoked: 'Нужен вход', error: 'Ошибка', waiting_qr: 'Ожидает QR', waiting_2fa: 'Ожидает 2FA', waiting_name: 'Нужно имя', connecting: 'Подключение'})[status] || status;
}

function renderSummary() {
  const summary = data.summary;
  $('readyAccounts').textContent = summary.accounts.ready;
  $('totalAccounts').textContent = `из ${summary.accounts.total} настроенных`;
  $('readyBots').textContent = summary.bots.ready;
  $('totalBots').textContent = summary.bots.total ? `из ${summary.bots.total} настроенных` : 'необязательно';
  $('accountsNavCount').textContent = summary.accounts.total;
  $('botsNavCount').textContent = summary.bots.total;
  const now = new Date();
  $('lastSync').textContent = new Intl.DateTimeFormat('ru-RU', {day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit'}).format(now);
  $('syncLabel').textContent = 'Данные актуальны';
}

function renderIdentities() {
  const rows = [...data.accounts.map((row) => ({...row, type: 'account'})), ...data.bots.map((row) => ({...row, type: 'bot'}))];
  const target = $('identityStrip');
  target.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement('div'); empty.className = 'identity-empty'; empty.textContent = 'Подключите первый аккаунт — он появится здесь.'; target.append(empty); return;
  }
  rows.slice(0, 3).forEach((row) => {
    const card = document.createElement('button'); card.className = 'identity-mini'; card.type = 'button'; card.onclick = () => navigate(row.type === 'bot' ? 'bots' : 'accounts');
    const isBot = row.type === 'bot';
    card.innerHTML = `<span class="identity-avatar ${isBot ? 'bot' : ''}"><i class="ph ${isBot ? 'ph-robot' : 'ph-user'}" aria-hidden="true"></i></span><span><strong></strong><small></small><span class="identity-status"><span class="live-dot"></span></span></span><i class="ph ph-caret-right identity-chevron" aria-hidden="true"></i>`;
    q('strong', card).textContent = row.label || (isBot ? 'Бот' : 'Аккаунт');
    q('small', card).textContent = identityHandle(row);
    const status = q('.identity-status', card); status.append(document.createTextNode(statusLabel(row.status)));
    if (row.status !== 'ready') { status.style.color = row.status === 'disabled' ? '#8fa1b8' : '#f2b84b'; q('.live-dot', status).style.background = row.status === 'disabled' ? '#63778f' : '#f2b84b'; }
    target.append(card);
  });
}

function seriesForRange() {
  if (selectedDays === 1) return data?.analytics?.hourly_series || [];
  return (data?.analytics?.series || []).slice(-selectedDays);
}

function renderAnalytics() {
  const analytics = data.analytics;
  const series = seriesForRange();
  const totals = series.reduce((sum, row) => ({read: sum.read + row.read, search: sum.search + row.search, send: sum.send + row.send}), {read: 0, search: 0, send: 0});
  const relevantDates = new Set(series.map((row) => row.date));
  const recent = selectedDays === 1
    ? analytics.recent.filter((event) => new Date(event.at).getTime() >= Date.now() - 24 * 60 * 60 * 1000)
    : analytics.recent.filter((event) => relevantDates.has(event.at.slice(0, 10)));
  const errors = recent.filter((event) => event.status === 'error').length;
  const requests = totals.read + totals.search + totals.send;
  const rate = requests ? errors / requests * 100 : 0;
  $('chartPeriodLabel').textContent = selectedDays === 1 ? 'За последние 24 часа' : `За последние ${selectedDays} дней`;
  $('usagePeriod').textContent = selectedDays === 1 ? 'За последние 24 часа' : `За последние ${selectedDays} дней`;
  $('requestsTotal').textContent = formatNumber(requests);
  $('readsTotal').textContent = formatNumber(totals.read);
  $('sendsTotal').textContent = formatNumber(totals.send);
  $('errorRate').textContent = `${rate.toLocaleString('ru-RU', {maximumFractionDigits: 1})}%`;
  $('successRate').textContent = `${Math.max(0, 100 - rate).toLocaleString('ru-RU', {maximumFractionDigits: 1})}%`;
  $('successBar').style.width = `${Math.max(0, 100 - rate)}%`;
  $('chartEmpty').hidden = requests !== 0;
  renderHistory();
  renderUsage();
  startChartAnimation();
}

function chartPath(ctx, points, waveTime, seriesIndex) {
  if (!points.length) return;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  points.slice(1).forEach((point, index) => {
    const previous = points[index];
    const distance = point.x - previous.x;
    const previousWave = reducedChartMotion.matches
      ? 0
      : Math.sin(waveTime + index * 0.78 + seriesIndex * 1.65) * 1.65;
    const nextWave = reducedChartMotion.matches
      ? 0
      : Math.sin(waveTime + (index + 1) * 0.78 + seriesIndex * 1.65) * 1.65;
    ctx.bezierCurveTo(
      previous.x + distance * 0.38,
      previous.y + previousWave,
      point.x - distance * 0.38,
      point.y + nextWave,
      point.x,
      point.y,
    );
  });
}

function chartAreaPath(ctx, points, baseline, waveTime, seriesIndex) {
  chartPath(ctx, points, waveTime, seriesIndex);
  if (!points.length) return;
  ctx.lineTo(points.at(-1).x, baseline);
  ctx.lineTo(points[0].x, baseline);
  ctx.closePath();
}

function colorWithAlpha(color, alpha) {
  const value = Number.parseInt(color.slice(1), 16);
  return `rgba(${value >> 16}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

function drawChart(timestamp = performance.now()) {
  const canvas = $('activityChart');
  if (!canvas || !canvas.offsetParent || !data) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * dpr); canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
  const width = rect.width, height = rect.height, pad = {left: 40, right: 12, top: 10, bottom: 28};
  const plotW = width - pad.left - pad.right, plotH = height - pad.top - pad.bottom;
  const series = seriesForRange();
  const maxRaw = Math.max(1, ...series.flatMap((row) => [row.read, row.search, row.send]));
  const max = Math.max(4, Math.ceil(maxRaw / 4) * 4);
  ctx.font = '9px InterVariable, sans-serif'; ctx.textBaseline = 'middle';
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + plotH * i / 4;
    ctx.strokeStyle = '#1c3044'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.fillStyle = '#687e96'; ctx.textAlign = 'right'; ctx.fillText(String(Math.round(max * (4 - i) / 4)), pad.left - 9, y);
  }
  if (!series.length) return;
  const step = series.length > 1 ? plotW / (series.length - 1) : plotW;
  const labelEvery = Math.max(1, Math.ceil(series.length / 7));
  series.forEach((row, index) => {
    if (index % labelEvery !== 0 && index !== series.length - 1) return;
    const x = series.length > 1 ? pad.left + index * step : pad.left + plotW / 2;
    ctx.fillStyle = '#687e96'; ctx.textAlign = 'center'; ctx.fillText(formatBucket(row.at || row.date, selectedDays), x, height - 10);
  });
  const waveTime = timestamp / 1550;
  const renderedSeries = [['read', '#4b92ff'], ['search', '#42d3eb'], ['send', '#9b78ff']].map(([key, color], seriesIndex) => {
    const points = series.map((row, index) => {
      const x = series.length > 1 ? pad.left + index * step : pad.left + plotW / 2;
      const y = pad.top + plotH - row[key] / max * plotH;
      return {x, y};
    });
    return {color, points, seriesIndex};
  });

  renderedSeries.forEach(({color, points, seriesIndex}) => {
    if (points.length < 2) return;
    const baseline = pad.top + plotH;
    const top = Math.min(...points.map((point) => point.y));
    const gradient = ctx.createLinearGradient(0, top, 0, baseline);
    gradient.addColorStop(0, colorWithAlpha(color, 0.2));
    gradient.addColorStop(0.58, colorWithAlpha(color, 0.065));
    gradient.addColorStop(1, colorWithAlpha(color, 0.008));

    ctx.save();
    chartAreaPath(ctx, points, baseline, waveTime * 0.72 + 1.1, seriesIndex);
    ctx.fillStyle = colorWithAlpha(color, reducedChartMotion.matches ? 0.025 : 0.045);
    ctx.fill();
    chartAreaPath(ctx, points, baseline, waveTime, seriesIndex);
    ctx.fillStyle = gradient;
    ctx.fill();
    ctx.restore();
  });

  renderedSeries.forEach(({color, points, seriesIndex}) => {
    ctx.save();
    ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    chartPath(ctx, points, waveTime, seriesIndex);
    ctx.strokeStyle = color; ctx.lineWidth = 7; ctx.globalAlpha = 0.1;
    ctx.stroke();

    chartPath(ctx, points, waveTime, seriesIndex);
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.globalAlpha = 1;
    ctx.shadowColor = color;
    ctx.shadowBlur = reducedChartMotion.matches
      ? 4
      : 5.5 + Math.sin(waveTime * 0.72 + seriesIndex) * 1.4;
    ctx.stroke();
    ctx.restore();

    points.forEach((point, index) => {
      const pulse = reducedChartMotion.matches
        ? 0
        : Math.sin(waveTime * 1.15 + index * 0.7 + seriesIndex) * 0.22;
      ctx.fillStyle = color; ctx.beginPath(); ctx.arc(point.x, point.y, 2.65 + pulse, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#0d1927'; ctx.lineWidth = 1; ctx.stroke();
    });
  });
}

function stopChartAnimation() {
  if (!chartAnimationFrame) return;
  cancelAnimationFrame(chartAnimationFrame);
  chartAnimationFrame = 0;
}

function startChartAnimation() {
  stopChartAnimation();
  const animate = (timestamp) => {
    drawChart(timestamp);
    const canvas = $('activityChart');
    if (!reducedChartMotion.matches && canvas?.offsetParent && document.visibilityState !== 'hidden') {
      chartAnimationFrame = requestAnimationFrame(animate);
    } else {
      chartAnimationFrame = 0;
    }
  };
  chartAnimationFrame = requestAnimationFrame(animate);
}

function filteredHistory() {
  const query = $('historySearch').value.trim().toLocaleLowerCase('ru');
  const identity = $('identityFilter').value, action = $('actionFilter').value, status = $('statusFilter').value;
  return (data?.analytics?.recent || []).filter((event) => {
    const copy = operationCopy[event.operation] || [event.operation, event.category, 'ph-circle'];
    const haystack = `${identityName(event.identity_id)} ${copy[0]} ${event.chat_id || ''}`.toLocaleLowerCase('ru');
    return (!query || haystack.includes(query)) && (!identity || event.identity_id === identity) && (!action || event.category === action) && (!status || event.status === status);
  });
}

let historyPage=1, historySize=10;
function renderHistory() {
  const rows = filteredHistory().sort((a,b)=>$('historySort').value==='oldest'?Date.parse(a.at)-Date.parse(b.at):$('historySort').value==='slow'?b.duration_ms-a.duration_ms:Date.parse(b.at)-Date.parse(a.at));
  const page=TgTables.paginate(rows,historyPage,historySize);historyPage=page.page;
  const target = $('historyRows'); target.replaceChildren();
  page.items.forEach((event) => {
    const copy = operationCopy[event.operation] || [event.operation, event.category, 'ph-circle'];
    const tr = document.createElement('tr');
    const values = [formatDateTime(event.at), identityName(event.identity_id), copy[0], event.chat_id || '—'];
    values.forEach((value, index) => { const td = document.createElement('td'); td.textContent = value; if (index === 1) td.className = 'cell-account'; if (index === 2) { td.className = `cell-action ${copy[1]}-action`; td.innerHTML = `<i class="ph ${copy[2]}" aria-hidden="true"></i><span></span>`; q('span', td).textContent = value; } tr.append(td); });
    const status = document.createElement('td'); const pill = document.createElement('span'); pill.className = `status-pill ${event.status === 'error' ? 'error' : ''}`; pill.textContent = event.status === 'error' ? 'Ошибка' : 'Успешно'; status.append(pill); tr.append(status);
    const duration = document.createElement('td'); duration.textContent = event.duration_ms >= 1000 ? `${(event.duration_ms / 1000).toLocaleString('ru-RU', {maximumFractionDigits: 1})} с` : `${event.duration_ms} мс`; tr.append(duration); target.append(tr);
  });
  $('historyEmpty').hidden = rows.length !== 0;
  makePager('historyPager',page,(p,size)=>{historyPage=p;historySize=size;renderHistory();},false,` · последние ${data?.analytics?.recent?.length || 0} операций за 30 дней`);
}

function renderUsage() {
  const target = $('usageRows'); target.replaceChildren();
  const rows = data?.analytics?.by_identity || [];
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    [identityName(row.identity_id), row.requests, row.read, row.search, row.send, row.errors].forEach((value, index) => { const td = document.createElement('td'); td.textContent = index ? formatNumber(value) : value; if (!index) td.className = 'cell-account'; tr.append(td); });
    target.append(tr);
  });
  $('usageEmpty').hidden = rows.length !== 0;
}

function renderFilters() {
  const select=$('identityFilter'),selected=select.value,rows=[...data.accounts,...data.bots];
  const key=JSON.stringify(rows.map(r=>[r.account_id||r.bot_id,r.label,r.username]));
  if(select.dataset.optionsKey===key)return;
  select.replaceChildren(new Option('Все аккаунты',''));
  rows.forEach(row=>select.append(new Option(row.label||row.username||row.account_id||row.bot_id,row.account_id||row.bot_id)));
  select.value=rows.some(r=>(r.account_id||r.bot_id)===selected)?selected:'';select.dataset.optionsKey=key;
}

function iconButton(label, icon, handler, extra = '') {
  const button = document.createElement('button'); button.type = 'button'; button.className = `button ${extra}`.trim(); button.innerHTML = `<i class="ph ${icon}" aria-hidden="true"></i><span></span>`; q('span', button).textContent = label; button.onclick = handler; return button;
}

async function patchAccount(id, body) { await api(`/setup/api/accounts/${id}`, {method: 'PATCH', body: JSON.stringify(body)}); await refresh(); }

async function deleteAccount(row) {
  const name = row.username ? `@${row.username}` : (row.label || 'этот аккаунт');
  if (!window.confirm(`Удалить ${name} и его Telegram-сессию с сервера?`)) return;
  try {
    suppressAutoAccount = true;
    sessionStorage.setItem('tg-mcp-suppress-auto-account', '1');
    await api(`/setup/api/accounts/${row.account_id}`, {method: 'DELETE'});
    renderedWizardKey = null;
    showNotice('Аккаунт и его сессия удалены', true);
    await refresh();
  } catch (error) { showNotice(error.message); }
}

function wizard(row) {
  const card = document.createElement('article'); card.className = 'panel wizard-card';
  const visual = document.createElement('div'); visual.className = 'wizard-visual';
  const content = document.createElement('div'); content.className = 'wizard-content';
  const step = ['waiting_qr', 'connecting'].includes(row.status) ? 1 : row.status === 'waiting_2fa' ? 2 : 3;
  const titles = ['Вход по QR-коду', 'Пароль 2FA', 'Имя аккаунта'];
  content.innerHTML = `<span class="wizard-kicker">Шаг ${step} из 3</span><h3>${titles[step - 1]}</h3><div class="wizard-steps"><span class="wizard-step active"></span><span class="wizard-step ${step >= 2 ? 'active' : ''}"></span><span class="wizard-step ${step >= 3 ? 'active' : ''}"></span></div>`;
  if (step === 1) {
    if (row.qr_data_url) { const image = document.createElement('img'); image.src = row.qr_data_url; image.alt = 'QR-код для входа в Telegram'; visual.append(image); }
    else visual.innerHTML = '<div class="wizard-loading"><i class="ph ph-spinner-gap" aria-hidden="true"></i>Получаем QR-код…</div>';
    const p = document.createElement('p'); p.textContent = 'Откройте Telegram на телефоне и отсканируйте код. Страница обновится автоматически после входа.'; content.insertBefore(p, q('.wizard-steps', content));
    const hint = document.createElement('div'); hint.className = 'wizard-hint'; hint.innerHTML = '<i class="ph ph-device-mobile-camera" aria-hidden="true"></i><span>Telegram → Настройки → Устройства → Подключить устройство</span>'; content.append(hint);
  } else if (step === 2) {
    visual.classList.add('neutral'); visual.innerHTML = '<div class="wizard-loading"><i class="ph ph-lock-key" aria-hidden="true"></i>Защищено 2FA</div>';
    const p = document.createElement('p'); p.textContent = 'Введите облачный пароль Telegram. Это не код из SMS или приложения-аутентификатора; сервер пароль не сохраняет.'; content.insertBefore(p, q('.wizard-steps', content));
    if (row.password_hint) { const hint = document.createElement('div'); hint.className = 'wizard-hint'; hint.textContent = `Подсказка Telegram: ${row.password_hint}`; content.append(hint); }
    if (row.error === 'invalid_password') { const error = document.createElement('p'); error.className = 'wizard-error'; error.textContent = `Telegram отклонил пароль. Убедитесь, что он относится к аккаунту, которым отсканирован QR. Осталось попыток: ${row.password_attempts_remaining}.`; content.append(error); }
    const form = document.createElement('form'); form.className = 'wizard-form'; const input = document.createElement('input'); input.type = 'password'; input.placeholder = 'Пароль 2FA'; input.required = true; input.autocomplete = 'current-password'; const submit = iconButton('Продолжить', 'ph-arrow-right', null, 'primary'); submit.type = 'submit'; form.onsubmit = async (event) => { event.preventDefault(); try { await api(`/setup/api/accounts/${row.account_id}/password`, {method: 'POST', body: JSON.stringify({password: input.value})}); input.value = ''; await refresh(); } catch (error) { showNotice(error.message); } }; form.append(input, submit); content.append(form);
    content.append(iconButton('Начать заново', 'ph-qr-code', async () => { try { await api(`/setup/api/accounts/${row.account_id}/login`, {method: 'POST'}); await refresh(); } catch (error) { showNotice(error.message); } }, 'secondary'));
  } else if (row.status === 'waiting_name') {
    visual.classList.add('neutral'); visual.innerHTML = '<div class="wizard-loading"><i class="ph ph-user-circle-check" aria-hidden="true"></i>Telegram подключён</div>';
    const p = document.createElement('p'); p.textContent = row.username ? `Аккаунт @${row.username} авторизован. Задайте понятное имя для выбора в инструментах MCP.` : 'Аккаунт авторизован. Задайте понятное имя для выбора в инструментах MCP.'; content.insertBefore(p, q('.wizard-steps', content));
    const form = document.createElement('form'); form.className = 'wizard-form'; const input = document.createElement('input'); input.placeholder = 'Например, Личный или Работа'; input.maxLength = 64; input.required = true; const submit = iconButton('Завершить', 'ph-check', null, 'primary'); submit.type = 'submit'; form.onsubmit = async (event) => { event.preventDefault(); try { await patchAccount(row.account_id, {label: input.value}); } catch (error) { showNotice(error.message); } }; form.append(input, submit); content.append(form);
  } else {
    visual.classList.add('neutral'); visual.innerHTML = '<div class="wizard-loading"><i class="ph ph-warning-circle" aria-hidden="true"></i>Нужен новый вход</div>';
    const p = document.createElement('p'); p.className = 'wizard-error'; p.textContent = row.error || statusLabel(row.status); content.insertBefore(p, q('.wizard-steps', content));
    content.append(iconButton('Получить новый QR', 'ph-qr-code', async () => { try { await api(`/setup/api/accounts/${row.account_id}/login`, {method: 'POST'}); await refresh(); } catch (error) { showNotice(error.message); } }, 'primary'));
  }
  content.append(iconButton('Удалить аккаунт', 'ph-warning-circle', () => deleteAccount(row), 'danger'));
  card.append(visual, content); return card;
}

function entityCard(row, type) {
  const card = document.createElement('article'); card.className = 'panel entity-card'; const id = row.account_id || row.bot_id; const isBot = type === 'bot';
  card.innerHTML = `<div class="entity-card-head"><span class="identity-avatar ${isBot ? 'bot' : ''}"><i class="ph ${isBot ? 'ph-robot' : 'ph-user'}" aria-hidden="true"></i></span><div><h3></h3><span class="handle"></span></div></div><div class="entity-meta"><span>Статус <strong></strong></span><span>Identity ID <strong></strong></span></div><div class="entity-actions"></div>`;
  q('h3', card).textContent = row.label || (isBot ? 'Telegram-бот' : 'Аккаунт'); q('.handle', card).textContent = row.username ? `@${row.username}` : 'Без username'; const strongs = qa('.entity-meta strong', card); strongs[0].textContent = statusLabel(row.status); strongs[0].style.color = row.status === 'ready' ? '#48db91' : row.status === 'disabled' ? '#8fa1b8' : '#f2b84b'; strongs[1].textContent = id;
  const actions = q('.entity-actions', card); actions.append(iconButton(row.enabled ? 'Отключить' : 'Включить', row.enabled ? 'ph-pause' : 'ph-play', async () => { try { if (isBot) await api(`/setup/api/bots/${id}`, {method: 'PATCH', body: JSON.stringify({enabled: !row.enabled})}); else await patchAccount(id, {enabled: !row.enabled}); await refresh(); } catch (error) { showNotice(error.message); } }, 'secondary'));
  if (!isBot && row.enabled && ['revoked', 'error'].includes(row.status)) actions.append(iconButton('Новый QR', 'ph-qr-code', async () => { try { await api(`/setup/api/accounts/${id}/login`, {method: 'POST'}); await refresh(); } catch (error) { showNotice(error.message); } }, 'secondary'));
  if (!isBot) actions.append(iconButton('Удалить', 'ph-warning-circle', () => deleteAccount(row), 'danger'));
  return card;
}

function renderManagement() {
  const pending = data.accounts.find((row) => ['connecting', 'waiting_qr', 'waiting_2fa', 'waiting_name'].includes(row.status));
  const nextWizardKey = pending
    ? `${pending.account_id}:${pending.status}:${pending.qr_data_url || ''}:${pending.error || ''}:${pending.password_hint || ''}:${pending.password_attempts_remaining ?? ''}`
    : null;
  if (nextWizardKey !== renderedWizardKey) {
    $('wizard').replaceChildren(...(pending ? [wizard(pending)] : []));
    renderedWizardKey = nextWizardKey;
  }
  $('startAccount').hidden = Boolean(pending); $('headerConnect').hidden = Boolean(pending) || !$('sidebar').querySelector('[data-view="accounts"].active');
  const accounts = data.accounts.filter((row) => row !== pending); $('accounts').replaceChildren(...accounts.map((row) => entityCard(row, 'account')));
  $('bots').replaceChildren(...data.bots.map((row) => entityCard(row, 'bot')));
}

async function startAccount() {
  navigate('accounts');
  suppressAutoAccount = false;
  sessionStorage.removeItem('tg-mcp-suppress-auto-account');
  try { await api('/setup/api/accounts', {method: 'POST', body: '{}'}); await refresh(); } catch (error) { showNotice(error.message); }
}

const mediaTypeLabels = {photo:'Фото', video:'Видео', document:'Документы', audio:'Аудио', voice:'Голосовые', video_note:'Видеосообщения', sticker:'Стикеры', animation:'Анимации'};
const chatKinds = {private:'Личный', group:'Группа', channel:'Канал', unknown:'Уточняется'};
const chatStates = {error:'Ошибка загрузки', pending:'Загружается', ready:'Готово', off:'Выключено', paused:'Архив остановлен', account_off:'Аккаунт выключен'};
const ragFilters = {query:'', account:'', kind:'', state:'', rule:'', s3:'', sort:'state', reverse:false, page:1, size:10};
let selectedChat = null;
let rowEditor = null;
let lastVisibleChats = [];
let ingestionDirty = false;
let ingestionSaving = false;
let ingestionOptionsKey = '';
let ingestionRenderedKey = '';
const ragRowCache = new Map();
const pagerCache = new Map();
function element(tag, cls = '', text = '') {const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e;}
function chatKey(c) {return `${c.account}:${c.chat}`;}
function setSmall(cell, text, small = '') {
  if (!cell.firstElementChild) cell.append(element('span'), element('small'));
  cell.children[0].textContent = text; cell.children[1].textContent = small; cell.children[1].hidden = !small;
}
function makePager(id, page, change, locked = false, suffix = '') {
  let cache = pagerCache.get(id);
  if (!cache) {
    const target = $(id), summary = element('span'), controls = element('div', 'pager-controls');
    const label = element('label', '', 'На странице '), size = element('select'); size.setAttribute('aria-label', `Размер страницы: ${id === 'ragPager' ? 'чаты' : 'операции'}`);
    [10,25,50,100].forEach(n => size.append(new Option(n,n))); label.append(size);
    const previous = element('button', 'button', 'Назад'), next = element('button', 'button', 'Далее'), pages = element('span','pager-pages');
    previous.type = next.type = 'button'; previous.setAttribute('aria-label','Предыдущая страница'); next.setAttribute('aria-label','Следующая страница');
    controls.append(label, previous, pages, next); target.append(summary,controls);
    cache = {summary,size,previous,next,pages,key:''}; pagerCache.set(id,cache);
    size.onchange = () => change(1,Number(size.value)); previous.onclick = () => change(cache.page.page-1,cache.page.size); next.onclick = () => change(cache.page.page+1,cache.page.size);
  }
  cache.page = page; cache.summary.textContent = `Показано ${page.start}–${page.end} из ${formatNumber(page.total)}${suffix}`; cache.size.value = String(page.size);
  cache.size.disabled = locked; cache.previous.disabled = locked || page.page <= 1; cache.next.disabled = locked || page.page >= page.pages;
  const key = `${page.page}:${page.pages}:${locked}`;
  if (key !== cache.key) {
    const numbers = [...new Set([1,page.page-1,page.page,page.page+1,page.pages])].filter(n => n > 0 && n <= page.pages).sort((a,b)=>a-b);
    const nodes=[]; let last=0;
    numbers.forEach(n => {if (last && n-last>1) nodes.push(element('span','pager-gap','…')); const b=element('button', 'pager-number', String(n)); b.type='button'; b.disabled=locked; b.setAttribute('aria-label',`Страница ${n}`); if(n===page.page)b.setAttribute('aria-current','page'); b.onclick=()=>change(n,cache.page.size); nodes.push(b);last=n;});
    cache.pages.replaceChildren(...nodes); cache.key=key;
  }
}
function errorText(code) {
  const names = {rate_limited:'Пауза Telegram после ограничения', load_paused:'Ожидает своей очереди', media_worker_failed:'Файл не обработан, запланирован повтор', media_transfer_unavailable:'Передача файла временно недоступна', media_queue_unavailable:'Очередь файлов временно недоступна', storage_full:'Недостаточно свободного места', storage_integrity:'Проверка целостности файла не прошла', source_changed:'Исходный файл изменился', file_unavailable:'Исходный файл недоступен', unavailable:'Сервис временно недоступен'};
  return names[code] || 'Не удалось выполнить загрузку. Повторная попытка запланирована.';
}
function renderRagThroughput(rag, stale) {
  const metrics = rag.throughput || {}, unavailable = stale || !rag.running || ['stale','paused'].includes(metrics.state);
  const rate = n => unavailable || n == null ? '—' : n.toLocaleString('ru-RU',{maximumFractionDigits:2});
  $('ragIndexRate').textContent=rate(metrics.index_per_second); $('ragIncomingRate').textContent=rate(metrics.incoming_per_second); $('ragPending').textContent=rag.pending_messages == null ? '—' : formatNumber(rag.pending_messages);
  $('ragQueueRate').textContent=`Изменение очереди: ${rate(metrics.queue_per_second)} текстов/с.`;
  const etaCopy={warming:'Собираем замеры',growing:'Очередь растёт',stalled:'Не сокращается',complete:'Обработана',blocked:'Аккаунт недоступен',paused:'Приостановлена',stale:'Нет свежих данных'};
  let forecast=etaCopy[metrics.state] || etaCopy.warming;
  if(metrics.state==='draining' && Number.isFinite(metrics.eta_seconds)) {const m=Math.max(1,Math.ceil(metrics.eta_seconds/60)); forecast=m<60?`≈ ${m} мин`:m<1440?`≈ ${Math.floor(m/60)} ч ${m%60} мин`:`≈ ${Math.ceil(m/1440)} дн.`;}
  $('ragEta').textContent=stale?'Нет связи':!rag.running?etaCopy.paused:forecast;
  $('ragRateWindow').textContent=unavailable?'Нет свежих замеров.':metrics.window_seconds?`Среднее за ${Math.round(metrics.window_seconds)} с · оценка только для сохранённых текстов`:'Нужно минимум 30 секунд замеров';
  $('ragEtaNote').textContent='Оценка учитывает приток новых текстов. Полный остаток истории Telegram пока неизвестен.';
  const history=metrics.history || [];
  $('ragQueueFigure').dataset.available=String(!unavailable && history.length>=2);
  if(!unavailable && history.length>=2) {
    const first=history[0],last=history[history.length-1],values=history.map(p=>p.pending),low=Math.min(...values),high=Math.max(...values);
    $('ragQueueRange').textContent=`${formatNumber(first.pending)} → ${formatNumber(last.pending)} текстов · диапазон ${formatNumber(low)}–${formatNumber(high)}`;
    const age=s=>s>=60?`${Math.round(s/60)} мин назад`:`${Math.ceil(s)} с назад`;
    $('ragQueueStart').textContent=age(first.age_seconds);$('ragQueueEnd').textContent=age(last.age_seconds);
  } else {$('ragQueueRange').textContent=unavailable?'Нет свежих данных для графика':'История очереди · собираем замеры';$('ragQueueStart').textContent='';$('ragQueueEnd').textContent='';}
  drawRagQueue();
}
function drawRagQueue() {
  const canvas=$('ragQueueChart'); if(!canvas.offsetParent)return;
  const w=canvas.clientWidth,h=80,dpr=window.devicePixelRatio || 1; canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
  const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
  const history=data?.rag?.throughput?.history || [];
  if($('ragQueueFigure').dataset.available!=='true'||history.length<2)return;
  const values=history.map(p=>p.pending),lo=Math.min(...values),hi=Math.max(...values),first=history[0].age_seconds,span=first-history[history.length-1].age_seconds;
  ctx.strokeStyle='#203247';ctx.lineWidth=1;[8,40,72].forEach(y=>{ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();});
  ctx.strokeStyle='#4b92ff';ctx.lineWidth=2;ctx.beginPath();
  history.forEach((p,i)=>{const x=span?3+(w-6)*(first-p.age_seconds)/span:3,y=hi===lo?40:72-64*(p.pending-lo)/(hi-lo);if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y);});ctx.stroke();
  canvas.setAttribute('aria-label',$('ragQueueRange').textContent);
}
function ingestionSelection() {const kind=$('ingestionScope').value.slice(7);return data?.media?.defaults?.[kind];}
function loadIngestionRule(force=false) {
  const rule=ingestionSelection(),fixed=!rule || rule.kind==='private';
  $('ingestionControls').disabled=fixed || ingestionSaving || ragStale; $('ingestionSave').disabled=fixed || ingestionSaving || ragStale; $('ingestionInherit').hidden=true;
  $('ingestionOrigin').textContent=!rule?'Правила пока недоступны.':fixed?'Личные чаты: тексты и все типы вложений включены постоянно.':'Общее правило действует для чатов без собственного переопределения.';
  const signature=JSON.stringify(rule);if(!force&&signature===ingestionRenderedKey)return;ingestionRenderedKey=signature;
  $('ingestionRag').checked=Boolean(rule?.rag_enabled);$('ingestionS3').checked=Boolean(rule?.s3_enabled);
  $('ingestionTypes').replaceChildren(...Object.entries(mediaTypeLabels).map(([type,title])=>{const label=element('label'),input=element('input');input.type='checkbox';input.value=type;input.checked=Boolean(rule?.content_types?.includes(type));label.append(input,document.createTextNode(title));return label;}));
}
function renderIngestion(stale) {
  const m=data?.media;
  $('ingestionCancel').hidden=!ingestionDirty&&!ingestionSaving;
  $('mediaState').textContent=stale?'Нет связи с сервером. Показаны последние данные.':m?.status_error?'Не удалось прочитать состояние хранилища.':!m?.configured?'S3 не настроен. Правила сохраняются, файлы пока не выгружаются.':`S3: ${formatNumber(m.files_uploaded)} файлов сохранено · ${formatNumber((m.jobs?.pending || 0)+(m.jobs?.downloading || 0)+(m.jobs?.error || 0))} в очереди · ${formatNumber(m.jobs?.error)} с ошибками · ${formatNumber(m.pending_deletions)} ожидают удаления.${m.last_error?' '+errorText(m.last_error):''}${m.deletion_errors?' Есть ошибки удаления.':''}`;
  $('settingsModel').textContent=data?.rag?.embedding_model || 'Не настроена';$('settingsS3').textContent=m?.configured?'Подключено':m?.status_error?'Состояние недоступно':'Не настроено';
  if(!ingestionOptionsKey && m?.defaults) {['private','group','channel'].forEach(k=>$('ingestionScope').append(new Option(chatKinds[k],`global:${k}`)));$('ingestionScope').value='global:group';ingestionOptionsKey='global:group';}
  if(!ingestionDirty&&!ingestionSaving)loadIngestionRule();
  else {const fixed=!ingestionSelection()||ingestionSelection().kind==='private';$('ingestionControls').disabled=fixed||ingestionSaving||stale;$('ingestionSave').disabled=fixed||ingestionSaving||stale;}
  const errors=(m?.jobs?.error || 0)+(m?.deletion_errors || 0);
  $('ragAlert').classList.toggle('has-errors',Boolean(errors || m?.last_error || m?.status_error));
  $('ragAlertText').textContent=stale?'Нет связи с сервером':m?.status_error?'Состояние S3 недоступно':errors?`${formatNumber(errors)} файлов требуют внимания · повтор запланирован`:m?.last_error?errorText(m.last_error):!m?.configured?'S3 не настроен':!m.running?'Задачи S3 остановлены':`${formatNumber(m.files_uploaded)} файлов в S3 · ${formatNumber((m.jobs?.pending || 0)+(m.jobs?.downloading || 0))} в очереди`;
}
async function saveIngestion() {
  const rule=ingestionSelection();if(!rule || rule.kind==='private'||ingestionSaving||ragStale)return;
  ingestionSaving=true;$('ingestionCancel').disabled=true;$('ingestionControls').disabled=true;$('ingestionSave').disabled=true;$('ingestionScope').disabled=true;$('ingestionResult').textContent='Сохраняем…';
  try{await api('/setup/api/ingestion-policy',{method:'POST',body:JSON.stringify({kind:rule.kind,rag_enabled:$('ingestionRag').checked,s3_enabled:$('ingestionS3').checked,content_types:qa('#ingestionTypes input:checked').map(i=>i.value)})});ingestionDirty=false;$('ingestionResult').textContent='Общее правило сохранено. Индивидуальные переопределения продолжают действовать.';}
  catch(error){$('ingestionResult').textContent=`Не удалось сохранить: ${error.message}. Повторите попытку.`;}
  finally{ingestionSaving=false;$('ingestionCancel').disabled=false;$('ingestionScope').disabled=false;await refresh();const fixed=!ingestionSelection()||ingestionSelection().kind==='private';$('ingestionControls').disabled=fixed||ragStale;$('ingestionSave').disabled=fixed||ragStale;}
}
function allRagChats() {
  const stats=new Map((data?.rag?.chats || []).map(c=>[chatKey(c),c]));
  const accounts=new Map((data?.accounts || []).map(a=>[a.account_id,a]));
  return (data?.media?.chats || []).map(c=>({...c,...stats.get(chatKey(c)),rag_enabled:c.rag_enabled,s3_enabled:c.s3_enabled,enabled:c.enabled,kind:c.kind,accountName:accounts.get(c.account)?.label || c.account,accountEnabled:accounts.get(c.account)?.enabled!==false,mediaConfigured:Boolean(data?.media?.configured),ragRunning:Boolean(data?.rag?.enabled&&data?.rag?.running),mediaRunning:Boolean(data?.media?.running)}));
}
function renderFacet(target,legend,options,current,change) {
  const el=$(target),key=options.map(o=>o.value).join('|');
  if(el.dataset.key!==key){const group=element('div');group.append(element('h3','',legend));options.forEach(o=>{const b=element('button','facet-button');b.type='button';b.dataset.value=o.value;b.append(element('span'),element('small'));b.onclick=()=>change(o.value);group.append(b);});el.replaceChildren(group);el.dataset.key=key;}
  qa('button',el).forEach((b,i)=>{const o=options[i];b.children[0].textContent=o.label;const ico=element('i',`ph ${target==='ragAccountFacets'?'ph-user':target==='ragKindFacets'?(o.value==='private'?'ph-user':o.value==='channel'?'ph-paper-plane-tilt':'ph-users'):o.value==='error'?'ph-warning-circle':o.value==='ready'?'ph-check':o.value==='off'?'ph-pause':'ph-clock-counter-clockwise'}`);b.children[0].prepend(ico);b.children[1].textContent=formatNumber(o.count);b.setAttribute('aria-pressed',String(current===o.value));b.disabled=Boolean(rowEditor?.dirty||rowEditor?.saving);});
}
function changeRagFilter(key,value) {if(rowEditor?.dirty||rowEditor?.saving)return;selectedChat=null;rowEditor=null;ragFilters[key]=value;ragFilters.page=1;ragFilters.reverse=false;renderRagTable();}
function createPolicyEditor(chat) {
  const box=element('div','inline-policy'),meta=element('div','policy-meta'),form=element('form','inline-policy-form');
  meta.append(element('h3','',chat.title || chat.chat),element('p','rag-muted',`${chatKinds[chat.kind] || chatKinds.unknown} · ${chat.accountName}`),element('code','',`ID: ${chat.chat}`),element('p','rag-muted','Изменения применяются только к этому чату. Существующие данные сохраняются.'));
  const origin=element('p','policy-origin'),fieldset=element('fieldset');fieldset.append(element('legend','','Правила загрузки'));
  function toggle(title,description,value) {const label=element('label','policy-toggle'),copy=element('span'),input=element('input');input.type='checkbox';input.setAttribute('role','switch');input.checked=value;copy.append(element('strong','',title),element('small','',description));label.append(input,copy);fieldset.append(label);return input;}
  const rag=toggle('Загружать тексты в RAG','Тексты сообщений сохраняются и попадают в индекс.',Boolean(chat.rag_enabled));
  const s3=toggle('Загружать вложения в S3','Сохраняются оригинальные файлы выбранных типов.',Boolean(chat.s3_enabled));
  fieldset.append(element('p','policy-types-title','Разрешённые типы вложений'));
  const types=element('div','policy-types');Object.entries(mediaTypeLabels).forEach(([type,title])=>{const label=element('label'),input=element('input');input.type='checkbox';input.value=type;input.checked=chat.content_types.includes(type);label.append(input,document.createTextNode(title));types.append(label);});fieldset.append(types,element('p','rag-muted','Типы применяются при включённом S3. Без распознавания изображений и расшифровки аудио.'));
  const actions=element('div','policy-actions'),inherit=element('button','text-button','Использовать общее правило'),cancel=element('button','button','Отменить изменения'),save=element('button','button primary','Сохранить правило'),result=element('p','policy-result');result.setAttribute('role','status');inherit.type=cancel.type='button';save.type='submit';actions.append(inherit,cancel,save);meta.append(origin);form.append(fieldset,actions,result);box.append(meta,form);
  const editor={box,chat:{...chat},origin,form,fieldset,rag,s3,types,inherit,cancel,save,result,dirty:false,saving:false,signature:JSON.stringify([chat.rag_enabled,chat.s3_enabled,chat.content_types,chat.inherited])};
  form.onchange=()=>{editor.dirty=true;result.textContent='Есть несохранённые изменения. Сохраните или отмените их перед переходом к другому чату.';lockRagControls();};
  cancel.onclick=()=>{selectedChat=null;rowEditor=null;renderRagTable();ragRowCache.get(chatKey(chat))?.button.focus();};
  form.onsubmit=e=>{e.preventDefault();savePolicyEditor(editor,false);};inherit.onclick=()=>savePolicyEditor(editor,true);
  updatePolicyEditor(editor,chat);return editor;
}
function updatePolicyEditor(editor,chat) {
  const fixed=!chat||!['group','channel'].includes(chat.kind),signature=chat?JSON.stringify([chat.rag_enabled,chat.s3_enabled,chat.content_types,chat.inherited]):'';
  if(chat&&!editor.dirty&&!editor.saving&&signature!==editor.signature){editor.rag.checked=Boolean(chat.rag_enabled);editor.s3.checked=Boolean(chat.s3_enabled);qa('input',editor.types).forEach(i=>i.checked=chat.content_types.includes(i.value));editor.signature=signature;}
  editor.chat=chat || editor.chat;editor.origin.textContent=!chat?'Чат больше не доступен. Черновик сохранён до отмены.':fixed?chat.kind==='private'?'Личный чат: тексты и все файлы включены постоянно.':'Тип чата ещё уточняется. Дождитесь обновления списка.':chat.inherited?'Действует общее правило. Сохранение создаст переопределение для чата.':'Своё правило: общее правило этого типа чатов не применяется.';
  editor.fieldset.disabled=fixed||editor.saving||ragStale;editor.save.disabled=fixed||editor.saving||ragStale;editor.inherit.disabled=fixed||editor.saving||ragStale||chat?.inherited;editor.cancel.disabled=editor.saving;editor.cancel.textContent=editor.dirty?'Отменить изменения':'Закрыть';
  editor.save.textContent=editor.saving?'Сохраняем…':'Сохранить правило';
}
async function savePolicyEditor(editor,inherit) {
  if(editor.saving||editor.save.disabled)return;
  editor.saving=true;editor.result.textContent='Сохраняем…';updatePolicyEditor(editor,editor.chat);lockRagControls();
  const c=editor.chat;
  try {await api('/setup/api/ingestion-policy',{method:'POST',body:JSON.stringify({account:c.account,chat:c.chat,kind:c.kind,rag_enabled:editor.rag.checked,s3_enabled:editor.s3.checked,content_types:qa('input:checked',editor.types).map(i=>i.value),inherit})});editor.dirty=false;editor.result.textContent='Правило сохранено. Существующие данные сохранены.';await refresh();}
  catch(error){editor.result.textContent=`Не удалось сохранить: ${error.message}. Изменения сохранены в форме; повторите попытку.`;}
  finally{editor.saving=false;updatePolicyEditor(editor,allRagChats().find(x=>chatKey(x)===chatKey(c)));renderRagTable();}
}
function lockRagControls() {
  const locked=Boolean(rowEditor?.dirty||rowEditor?.saving);
  ['ragSearch','ragSort','ragRuleFilter','ragS3Filter','ragReset'].forEach(id=>$(id).disabled=locked);
  qa('.rag-facets button, [data-rag-sort]').forEach(b=>b.disabled=locked);
  ragRowCache.forEach(c=>{c.button.disabled=locked && c.key!==selectedChat;c.titleButton.disabled=c.button.disabled;});
  if(locked)qa('#ragPager button, #ragPager select').forEach(e=>e.disabled=true);
}
function renderRagTable() {
  const all=allRagChats(),lookup=new Map(all.map(c=>[chatKey(c),c]));
  if(rowEditor)updatePolicyEditor(rowEditor,lookup.get(selectedChat));
  const options=(values,key)=>values.map(([value,label])=>({value,label,count:value?all.filter(c=>key==='state'?(value==='off'?['off','paused','account_off'].includes(TgTables.stateOf(c)):TgTables.stateOf(c)===value):c[key]===value).length:all.length}));
  renderFacet('ragAccountFacets','Аккаунт',[{value:'',label:'Все',count:all.length},...(data?.accounts || []).map(a=>({value:a.account_id,label:a.label||a.account_id,count:all.filter(c=>c.account===a.account_id).length}))],ragFilters.account,v=>changeRagFilter('account',v));
  renderFacet('ragKindFacets','Тип чата',options([['','Все'],['private','Личные'],['group','Группы'],['channel','Каналы'],...(all.some(c=>c.kind==='unknown')?[['unknown','Уточняются']]:[])],'kind'),ragFilters.kind,v=>changeRagFilter('kind',v));
  renderFacet('ragStateFacets','Состояние',options([['','Все'],['pending','Загружаются'],['error','С ошибками'],['ready','Готовы'],['off','Выключены']],'state'),ragFilters.state,v=>changeRagFilter('state',v));
  const filtered=TgTables.selectChats(all,ragFilters),page=TgTables.paginate(filtered,ragFilters.page,ragFilters.size);ragFilters.page=page.page;
  if(rowEditor)page.items=lastVisibleChats.map(k=>lookup.get(k)||(k===selectedChat?rowEditor.chat:null)).filter(Boolean);else lastVisibleChats=page.items.map(chatKey);
  document.querySelector('.rag-result-line').hidden=!['query','account','kind','state','rule','s3'].some(k=>ragFilters[k]);
  $('ragChatHeading').textContent=`Чаты (${formatNumber(all.length)})`;$('ragChatSummary').textContent=filtered.length===all.length?`Все ${formatNumber(all.length)} чатов · личные, группы и каналы`:`По фильтрам: ${formatNumber(filtered.length)} из ${formatNumber(all.length)}`;
  const wanted=[];
  page.items.forEach(c=>{
    const key=chatKey(c);let cached=ragRowCache.get(key);
    if(!cached){const tr=element('tr'),cells=Array.from({length:8},()=>element('td')),button=element('button','row-disclosure');button.type='button';button.append(element('i','ph ph-caret-right'));button.onclick=()=>{if(rowEditor?.dirty||rowEditor?.saving){showNotice('Сначала сохраните или отмените текущее правило.');return;}if(selectedChat===key){selectedChat=null;rowEditor=null;}else{selectedChat=key;rowEditor=createPolicyEditor(allRagChats().find(x=>chatKey(x)===key));}renderRagTable();};const titleButton=element('button','chat-title-button');titleButton.type='button';titleButton.onclick=()=>button.click();cells[0].append(titleButton,element('small'));cells[7].append(button);tr.append(...cells);cached={key,tr,cells,button,titleButton,detail:element('tr','policy-detail-row')};const td=element('td');td.colSpan=8;cached.detail.append(td);ragRowCache.set(key,cached);}
    const {tr,cells,button,detail}=cached,state=TgTables.stateOf(c);tr.classList.toggle('selected',key===selectedChat);tr.dataset.state=state;
    cached.titleButton.title=c.title||c.chat;setSmall(cells[0],c.title||c.chat,c.kind==='private'?'Фиксированное правило':c.inherited?'Общее правило':'Своё правило');
    cells[1].textContent=c.accountName;cells[2].textContent=chatKinds[c.kind]||chatKinds.unknown;
    setSmall(cells[3],!c.rag_enabled?(c.s3_enabled?'Только файлы':'Выключена'):c.backfill_complete?'До начала':c.last_sync?'Загружается':'Ожидает загрузки',c.last_sync?formatDateTime(c.last_sync):'');
    setSmall(cells[4],!c.rag_enabled?'Выключен':c.indexed==null?'Нет данных':formatNumber(c.indexed),c.rag_enabled&&c.eligible!=null?`из ${formatNumber(c.eligible)} текстов`:'');
    setSmall(cells[5],!c.s3_enabled?'Выключены':!c.mediaConfigured?'S3 не настроен':`${formatNumber(c.media_uploaded)} файлов`,c.s3_enabled&&c.mediaConfigured?`${formatNumber(c.media_pending)} в очереди`:'');
    setSmall(cells[6],chatStates[state],c.error?errorText(c.error):c.media_errors?'Повтор запланирован':'');cells[6].className=`chat-state ${state}`;
    button.setAttribute('aria-label',`${key===selectedChat?'Закрыть':'Открыть'} правило: ${c.title||c.chat}`);button.setAttribute('aria-expanded',String(key===selectedChat));
    wanted.push(tr);
    if(key===selectedChat&&rowEditor){if(detail.firstChild.firstChild!==rowEditor.box)detail.firstChild.replaceChildren(rowEditor.box);wanted.push(detail);}
  });
  if(!wanted.length){const tr=element('tr'),td=element('td','table-empty',data?.media?.status_error?'Список чатов временно недоступен.':all.length?'По этим фильтрам чатов нет. Сбросьте фильтры или измените запрос.':'Чаты ещё не обнаружены.');td.colSpan=8;tr.append(td);wanted.push(tr);}
  // Keep the expanded editor connected: polling must preserve focused inputs and drafts.
  const body=$('ragChats'),keep=new Set(wanted);let cursor=body.firstChild;
  wanted.forEach(node=>{if(cursor===node)cursor=cursor.nextSibling;else body.insertBefore(node,cursor);});[...body.childNodes].forEach(n=>{if(!keep.has(n))n.remove();});
  for(const [key,value] of ragRowCache)if(!lookup.has(key)&&key!==selectedChat){value.tr.remove();ragRowCache.delete(key);}
  makePager('ragPager',page,(p,size)=>{if(rowEditor?.dirty||rowEditor?.saving)return;selectedChat=null;rowEditor=null;ragFilters.page=p;ragFilters.size=size;renderRagTable();},Boolean(rowEditor?.dirty||rowEditor?.saving));
  qa('[data-rag-sort]').forEach(b=>b.parentNode.setAttribute('aria-sort',b.dataset.ragSort===ragFilters.sort?((['pending','recent'].includes(ragFilters.sort)!==ragFilters.reverse)?'descending':'ascending'):'none'));lockRagControls();
}
function renderRag(stale=ragStale) {
  ragStale=stale;renderIngestion(stale);const rag=data?.rag || {},state=$('ragState');
  state.classList.toggle('rag-warning',Boolean(stale||rag.last_error||rag.status_error));
  state.textContent=stale?'Нет связи с сервером. Показаны последние данные.':rag.status_error?'Состояние индексации временно недоступно.':!rag.enabled?'Фоновый RAG выключен в конфигурации сервера.':!rag.running?'Фоновые задачи остановлены.':rag.last_error?errorText(rag.last_error):`Индекс обновляется · ${formatNumber(rag.ready_accounts)} аккаунта готовы`;
  renderRagThroughput(rag,stale||Boolean(rag.status_error));
  const count=n=>n==null?'—':formatNumber(n),date=v=>v?formatDateTime(v):'—';
  $('ragHistory').textContent=`История достигла начала в ${count(rag.history_complete_chats)} из ${count(rag.selected_chats)} активных чатов · сохранено ${count(rag.archived_messages)} сообщений. Полный остаток Telegram пока неизвестен.`;
  $('ragIndex').textContent=`В индексе ${count(rag.indexed_messages)} из ${count(rag.eligible_messages)} сохранённых текстов · осталось ${count(rag.pending_messages)}.`;
  $('ragModel').textContent=`Локальная модель: ${rag.embedding_model || 'не настроена'}. Пустые сообщения не индексируются.`;
  $('ragTimes').textContent=`Обнаружение: ${date(rag.last_discovery)} · индексация: ${date(rag.last_index)} · снимок: ${date(rag.observed_at)}`;
  $('ragAccounts').replaceChildren(...(data?.accounts || []).map(a=>{const p=(rag.loading || []).find(p=>p.account===a.account_id),tr=element('tr');[a.label||a.account_id,p?.interval==null?'—':`${p.interval.toLocaleString('ru-RU',{maximumFractionDigits:1})} с`,p?.cooldown_until*1000>Date.now()?date(p.cooldown_until*1000):'Нет паузы',p?.last_limited?date(p.last_limited*1000):'—',count(p?.limits)].forEach(v=>tr.append(element('td','',v)));return tr;}));
  renderRagTable();
}
$('ingestionScope').onchange=()=>{if(ingestionDirty){$('ingestionScope').value=ingestionOptionsKey;showNotice('Сначала сохраните или отмените изменения общего правила.');return;}ingestionOptionsKey=$('ingestionScope').value;$('ingestionResult').textContent='';loadIngestionRule();};
$('ingestionControls').onchange=()=>{$('ingestionCancel').hidden=false;ingestionDirty=true;$('ingestionScope').disabled=true;};
$('ingestionForm').onsubmit=e=>{e.preventDefault();saveIngestion();};$('ingestionInherit').onclick=()=>{};
$('ingestionCancel').onclick=()=>{if(ingestionSaving)return;$('ingestionCancel').hidden=true;ingestionDirty=false;$('ingestionScope').disabled=false;$('ingestionResult').textContent='Изменения отменены.';loadIngestionRule(true);};
$('ragSearch').oninput=()=>changeRagFilter('query',$('ragSearch').value);
$('ragSort').onchange=()=>changeRagFilter('sort',$('ragSort').value);
$('ragRuleFilter').onchange=()=>changeRagFilter('rule',$('ragRuleFilter').value);
$('ragS3Filter').onchange=()=>changeRagFilter('s3',$('ragS3Filter').value);
$('ragReset').onclick=()=>{if(rowEditor?.dirty||rowEditor?.saving)return;selectedChat=null;rowEditor=null;Object.assign(ragFilters,{query:'',account:'',kind:'',state:'',rule:'',s3:'',sort:'state',reverse:false,page:1});$('ragSearch').value='';$('ragSort').value='state';$('ragRuleFilter').value=$('ragS3Filter').value='';renderRagTable();};
qa('[data-rag-sort]').forEach(b=>b.onclick=()=>{if(rowEditor?.dirty||rowEditor?.saving)return;selectedChat=null;rowEditor=null;if(ragFilters.sort===b.dataset.ragSort)ragFilters.reverse=!ragFilters.reverse;else{ragFilters.sort=b.dataset.ragSort;ragFilters.reverse=false;}ragFilters.page=1;$('ragSort').value=ragFilters.sort;renderRagTable();});
$('ragMoreFilters').onclick=()=>{const open=$('ragExtraFilters').hidden;$('ragExtraFilters').hidden=!open;$('ragMoreFilters').setAttribute('aria-expanded',String(open));};
$('ragAlert').onclick=()=>{const open=$('ragDiagnostics').hidden;$('ragDiagnostics').hidden=!open;$('ragAlert').setAttribute('aria-expanded',String(open));};
['Rules','Info'].forEach(name=>{const tab=$(`settings${name}Tab`);tab.onclick=()=>{['Rules','Info'].forEach(n=>{$(`settings${n}`).hidden=n!==name;$(`settings${n}Tab`).setAttribute('aria-selected',String(n===name));$(`settings${n}Tab`).tabIndex=n===name?0:-1;});};tab.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?'Rules':e.key==='End'?'Info':name==='Rules'?'Info':'Rules';$(`settings${next}Tab`).click();$(`settings${next}Tab`).focus();}};});$('settingsInfoTab').tabIndex=-1;
window.addEventListener('resize',drawRagQueue);

async function refresh() {
  try {
    data = await api('/setup/api/status');
    $('versionLabel').textContent = data.version ? `TG MCP v${data.version}` : 'TG MCP';
    renderSummary(); renderIdentities(); renderFilters(); renderAnalytics(); renderManagement(); renderRag(false);
    if (!data.accounts.length && !autoStarting && !suppressAutoAccount) { autoStarting = true; await api('/setup/api/accounts', {method: 'POST', body: '{}'}); await refresh(); }
  } catch (error) {
    renderRag(true);
    $('syncLabel').textContent = 'Нет доступа к данным';
    showNotice(error.message);
  }
}

qa('.nav-item').forEach((button) => button.addEventListener('click', () => navigate(button.dataset.view)));
qa('[data-view-link]').forEach((button) => button.addEventListener('click', () => navigate(button.dataset.viewLink)));
$('mobileMenu').onclick = () => $('sidebar').classList.contains('open') ? closeSidebar() : openSidebar();
$('sidebarScrim').onclick = closeSidebar;
$('headerConnect').onclick = startAccount; $('startAccount').onclick = startAccount;
$('botForm').onsubmit = async (event) => { event.preventDefault(); try { await api('/setup/api/bots', {method: 'POST', body: JSON.stringify({label: $('botLabel').value, token: $('botToken').value})}); $('botLabel').value = ''; $('botToken').value = ''; showNotice('Бот подключён', true); await refresh(); } catch (error) { showNotice(error.message); } };
qa('#rangeSelector button').forEach((button) => button.addEventListener('click', () => { selectedDays = Number(button.dataset.days); qa('#rangeSelector button').forEach((item) => item.classList.toggle('active', item === button)); renderAnalytics(); }));
['historySearch', 'identityFilter', 'actionFilter', 'statusFilter','historySort'].forEach((id) => $(id).addEventListener(id === 'historySearch' ? 'input' : 'change', ()=>{historyPage=1;renderHistory();}));
qa('[data-table-tab]').forEach((button) => button.addEventListener('click', () => { qa('[data-table-tab]').forEach((item) => item.classList.toggle('active', item === button)); const history = button.dataset.tableTab === 'history'; $('historyToolbar').hidden = !history; $('historyTableWrap').hidden = !history; $('usageTableWrap').hidden = history; $('historyPager').hidden = !history; }));
qa('[data-copy="endpoint"]').forEach((button) => button.addEventListener('click', async () => { try { await navigator.clipboard.writeText(`${location.origin}/mcp`); showNotice('MCP endpoint скопирован', true); } catch { showNotice('Не удалось скопировать endpoint'); } }));
window.addEventListener('resize', startChartAnimation);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') stopChartAnimation();
  else startChartAnimation();
});
if (reducedChartMotion.addEventListener) {
  reducedChartMotion.addEventListener('change', startChartAnimation);
}

const endpoint = `${location.origin}/mcp`; $('endpointValue').textContent = endpoint.replace(/^https?:\/\//, ''); $('endpointFull').textContent = endpoint;
$('todayLabel').textContent = new Intl.DateTimeFormat('ru-RU', {day: 'numeric', month: 'long', year: 'numeric'}).format(new Date());

if (viewCopy[location.hash.slice(1)]) navigate(location.hash.slice(1));
refresh(); setInterval(refresh, 4000);
