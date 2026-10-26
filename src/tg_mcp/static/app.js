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
  settings: ['Настройки', 'Хранение данных и приватность аналитики'],
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
  history.replaceState(null, '', view === 'rag' ? '#rag' : location.pathname);
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

function renderHistory() {
  const rows = filteredHistory();
  const target = $('historyRows'); target.replaceChildren();
  rows.forEach((event) => {
    const copy = operationCopy[event.operation] || [event.operation, event.category, 'ph-circle'];
    const tr = document.createElement('tr');
    const values = [formatDateTime(event.at), identityName(event.identity_id), copy[0], event.chat_id || '—'];
    values.forEach((value, index) => { const td = document.createElement('td'); td.textContent = value; if (index === 1) td.className = 'cell-account'; if (index === 2) { td.className = `cell-action ${copy[1]}-action`; td.innerHTML = `<i class="ph ${copy[2]}" aria-hidden="true"></i><span></span>`; q('span', td).textContent = value; } tr.append(td); });
    const status = document.createElement('td'); const pill = document.createElement('span'); pill.className = `status-pill ${event.status === 'error' ? 'error' : ''}`; pill.textContent = event.status === 'error' ? 'Ошибка' : 'Успешно'; status.append(pill); tr.append(status);
    const duration = document.createElement('td'); duration.textContent = event.duration_ms >= 1000 ? `${(event.duration_ms / 1000).toLocaleString('ru-RU', {maximumFractionDigits: 1})} с` : `${event.duration_ms} мс`; tr.append(duration); target.append(tr);
  });
  $('historyEmpty').hidden = rows.length !== 0;
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
  const select = $('identityFilter'); const selected = select.value;
  select.replaceChildren(new Option('Все аккаунты', ''));
  [...data.accounts, ...data.bots].forEach((row) => select.append(new Option(row.label || row.username || row.account_id || row.bot_id, row.account_id || row.bot_id)));
  select.value = selected;
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
  $('startAccount').hidden = Boolean(pending); $('headerConnect').hidden = Boolean(pending);
  const accounts = data.accounts.filter((row) => row !== pending); $('accounts').replaceChildren(...accounts.map((row) => entityCard(row, 'account')));
  $('bots').replaceChildren(...data.bots.map((row) => entityCard(row, 'bot')));
}

async function startAccount() {
  navigate('accounts');
  suppressAutoAccount = false;
  sessionStorage.removeItem('tg-mcp-suppress-auto-account');
  try { await api('/setup/api/accounts', {method: 'POST', body: '{}'}); await refresh(); } catch (error) { showNotice(error.message); }
}

function renderRagThroughput(rag, stale) {
  const metrics = rag.throughput || {};
  const unavailable = stale || !rag.running || ['stale', 'paused'].includes(metrics.state);
  const rate = (value, signed = false) => unavailable || value == null ? '—'
    : `${signed && value > 0 ? '+' : ''}${value.toLocaleString('ru-RU', {maximumFractionDigits: 2})} текстов/с`;
  $('ragIndexRate').textContent = rate(metrics.index_per_second);
  $('ragIncomingRate').textContent = rate(metrics.incoming_per_second, true);
  $('ragQueueRate').textContent = rate(metrics.queue_per_second, true);
  $('ragQueueRate').classList.toggle('rag-warning', !unavailable && metrics.queue_per_second > 0);
  const age = (seconds) => seconds >= 60 ? `${Math.round(seconds / 60)} мин назад` : `${Math.ceil(seconds)} с назад`;
  const history = metrics.history || [];
  $('ragRateWindow').textContent = unavailable ? 'Нет свежих замеров скорости.'
    : metrics.window_seconds ? `Средние скорости за ${Math.round(metrics.window_seconds)} с. Приток — изменение объёма сохранённых текстов с учётом удалений; очередь также учитывает правки.`
    : 'Нужно минимум 30 секунд замеров. После перезапуска или изменения состава чатов окно собирается заново.';
  const etaCopy = {
    warming: 'Собираем замеры…', growing: 'Очередь растёт при текущем притоке',
    stalled: 'Очередь пока не сокращается', complete: 'Текущая очередь обработана',
    blocked: 'Часть аккаунтов недоступна', paused: 'Индексация приостановлена',
    stale: 'Нет свежих замеров',
  };
  const eta = metrics.eta_seconds;
  let forecast = etaCopy[metrics.state] || etaCopy.warming;
  if (metrics.state === 'draining' && Number.isFinite(eta)) {
    const minutes = Math.max(1, Math.ceil(eta / 60));
    forecast = minutes < 60 ? `≈ ${minutes} мин` : minutes < 1440
      ? `≈ ${Math.floor(minutes / 60)} ч ${minutes % 60} мин`
      : `≈ ${Math.ceil(minutes / 1440)} дн.`;
  }
  $('ragEta').textContent = stale ? 'Нет связи с сервером' : !rag.running ? etaCopy.paused : forecast;
  $('ragEtaNote').textContent = 'Оценка учитывает чистое сокращение текущей очереди и наблюдаемый приток. Она меняется вместе с темпом; это не срок загрузки всей истории Telegram.';
  $('ragQueueFigure').hidden = unavailable || history.length < 2;
  if (!unavailable && history.length >= 2) {
    const first = history[0]; const last = history[history.length - 1];
    const values = history.map((point) => point.pending);
    const low = Math.min(...values); const high = Math.max(...values);
    const span = first.age_seconds - last.age_seconds;
    const points = history.map((point) => {
      const x = span ? 2 + 596 * (first.age_seconds - point.age_seconds) / span : 2;
      const y = high === low ? 40 : 74 - 68 * (point.pending - low) / (high - low);
      return `${x},${y}`;
    });
    $('ragQueueLine').setAttribute('points', points.join(' '));
    const delta = last.pending - first.pending;
    $('ragQueueRange').textContent = `${formatNumber(first.pending)} → ${formatNumber(last.pending)} текстов · изменение ${delta > 0 ? '+' : ''}${formatNumber(delta)} · диапазон графика ${formatNumber(low)}–${formatNumber(high)}`;
    $('ragQueueChart').setAttribute('aria-label', $('ragQueueRange').textContent);
    $('ragQueueStart').textContent = age(first.age_seconds);
    $('ragQueueEnd').textContent = age(last.age_seconds);
  }
}

const mediaTypeLabels = {photo:'Фото', video:'Видео', document:'Документы', audio:'Аудио', voice:'Голосовые', video_note:'Видеосообщения', sticker:'Стикеры', animation:'Анимации'};
let ingestionDirty = false;
let ingestionSaving = false;
let ingestionOptionsKey = '';
function ingestionSelection() {
  const value = $('ingestionScope').value;
  if (value.startsWith('global:')) return {kind:value.slice(7), ...(data?.media?.defaults?.[value.slice(7)] || {})};
  return data?.media?.chats?.find(c => `${c.account}:${c.chat}` === value);
}
function loadIngestionRule() {
  const rule = ingestionSelection();
  const fixed = !rule || rule.kind === 'private';
  $('ingestionControls').disabled = fixed || ingestionSaving;
  $('ingestionSave').disabled = fixed || ingestionSaving;
  $('ingestionInherit').disabled = fixed || !rule?.account || ingestionSaving;
  $('ingestionOrigin').textContent = !rule ? 'Выберите правило.' : fixed ? 'Личный чат: RAG и все вложения включены постоянно.' : rule.account ? (rule.inherited ? 'Действует общее правило.' : 'Для этого чата задано своё правило.') : 'Применяется к чатам без собственного правила, включая новые.';
  $('ingestionRag').checked = Boolean(rule?.rag_enabled);
  $('ingestionS3').checked = Boolean(rule?.s3_enabled);
  $('ingestionTypes').replaceChildren();
  Object.entries(mediaTypeLabels).forEach(([type, title]) => {
    const label = document.createElement('label');
    const input = document.createElement('input'); input.type = 'checkbox'; input.value = type;
    input.checked = Boolean(rule?.content_types?.includes(type));
    label.append(input, document.createTextNode(title)); $('ingestionTypes').append(label);
  });
}
function renderIngestion(stale) {
  const media = data?.media;
  $('mediaState').textContent = stale ? 'Нет связи с сервером. Состояние S3 могло устареть.' : media?.status_error ? 'Состояние S3 недоступно. Повторная попытка через 4 секунды.' : !media?.configured ? 'S3 не настроен. Правила сохраняются, файлы пока не выгружаются.' : `S3: ${formatNumber(media.files_uploaded || 0)} файлов сохранено · ${formatNumber((media.jobs?.pending || 0) + (media.jobs?.downloading || 0) + (media.jobs?.error || 0))} в очереди · ${formatNumber(media.jobs?.error || 0)} ошибок · ${formatNumber(media.pending_deletions || 0)} ожидают удаления${media.deletion_errors ? ' · есть ошибки удаления' : ''}${media.last_error ? ` · ${media.last_error}` : !media.running ? ' · задачи остановлены' : ''}.`;
  const choices = [['global:group','Общее правило: группы'],['global:channel','Общее правило: каналы'], ...(media?.chats || []).map(c => [`${c.account}:${c.chat}`, `${c.title || c.chat} · ${data.accounts.find(a => a.account_id === c.account)?.label || c.account}`])];
  const key = JSON.stringify(choices);
  if (key !== ingestionOptionsKey && !ingestionDirty && !ingestionSaving) {
    const selected = $('ingestionScope').value;
    $('ingestionScope').replaceChildren(...choices.map(([value,title]) => {const option = document.createElement('option');option.value=value;option.textContent=title;return option;}));
    if (choices.some(c => c[0] === selected)) $('ingestionScope').value = selected;
    ingestionOptionsKey = key;
  }
  if (!ingestionDirty && !ingestionSaving) loadIngestionRule();
}
$('ingestionScope').onchange = () => {ingestionDirty = false; $('ingestionResult').textContent = ''; loadIngestionRule();};
$('ingestionControls').onchange = () => {ingestionDirty = true;};
async function saveIngestion(inherit) {
  const rule = ingestionSelection(); if (!rule || rule.kind === 'private' || ingestionSaving) return;
  ingestionSaving = true; $('ingestionSave').disabled = true; $('ingestionInherit').disabled = true; $('ingestionControls').disabled = true; $('ingestionScope').disabled = true;
  $('ingestionResult').textContent = 'Сохраняем…';
  try {
    await api('/setup/api/ingestion-policy', {method:'POST', body:JSON.stringify({kind:rule.kind, account:rule.account || '', chat:rule.chat || '', rag_enabled:$('ingestionRag').checked, s3_enabled:$('ingestionS3').checked, content_types:[...$('ingestionTypes').querySelectorAll('input:checked')].map(i => i.value), inherit})});
    ingestionDirty = false;
    $('ingestionResult').textContent = 'Правило сохранено. Существующие данные сохраняются; новые типы вложений добавляются в очередь.';
  } catch (error) { $('ingestionResult').textContent = `Не удалось сохранить: ${error.message}. Повторите попытку.`; }
  finally {
    ingestionSaving = false; $('ingestionScope').disabled = false; await refresh();
    const current = ingestionSelection(); const fixed = !current || current.kind === 'private';
    $('ingestionControls').disabled = fixed; $('ingestionSave').disabled = fixed;
    $('ingestionInherit').disabled = fixed || !current?.account;
  }
}
$('ingestionForm').onsubmit = (event) => {event.preventDefault(); saveIngestion(false);};
$('ingestionInherit').onclick = () => saveIngestion(true);

function renderRag(stale = ragStale) {
  ragStale = stale;
  renderIngestion(stale);
  const rag = data?.rag;
  const state = $('ragState');
  const details = $('ragDetails');
  state.classList.toggle('rag-warning', stale || Boolean(rag?.status_error || rag?.last_error || rag?.chat_errors));
  if (!rag || rag.status_error || !rag.enabled) {
    details.hidden = true;
    state.textContent = stale ? 'Нет связи с сервером. Состояние RAG недоступно.'
      : rag?.status_error ? 'Не удалось прочитать состояние RAG. Повторная попытка через 4 секунды.'
      : rag ? 'Фоновый RAG выключен. Включите его в конфигурации сервера.' : 'Загрузка состояния RAG…';
    return;
  }
  details.hidden = false;
  state.textContent = stale ? 'Нет связи с сервером. Ниже последние полученные данные; они могли устареть.'
    : !rag.running ? 'Фоновые задачи остановлены.'
    : rag.last_error ? `Фоновая задача ожидает повторной попытки: ${rag.last_error}`
    : rag.chat_errors ? `RAG работает. Чатов с ограничениями или ошибками: ${formatNumber(rag.chat_errors)}. Подробности ниже.`
    : 'RAG работает. Данные обновляются каждые 4 секунды.';
  renderRagThroughput(rag, stale);
  const count = (value) => value == null ? '—' : formatNumber(value);
  const date = (value) => value ? formatDateTime(value) : '—';
  const epoch = (value) => value ? date(value * 1000) : '—';
  const accountName = (id) => data.accounts.find((a) => a.account_id === id)?.label || id;
  $('ragHistory').textContent = `${count(rag.selected_chats)} чатов · история загружена до начала в ${count(rag.history_complete_chats)} · ещё не загружались ${count(rag.never_synced_chats)} · сохранено ${count(rag.archived_messages)} сообщений`;
  $('ragIndex').textContent = `${count(rag.indexed_messages)} из ${count(rag.eligible_messages)} сохранённых текстов в индексе · осталось ${count(rag.pending_messages)}`;
  const progress = $('ragProgress');
  if (rag.pending_messages == null) progress.removeAttribute('value');
  else progress.value = rag.eligible_messages ? 100 * rag.indexed_messages / rag.eligible_messages : 0;
  $('ragModel').textContent = `Локальная модель: ${rag.embedding_model || '—'}. Пустые сообщения и сообщения без текста не входят в очередь индексации.`;
  $('ragTimes').textContent = `Обнаружение чатов: ${date(rag.last_discovery)} · индексация: ${date(rag.last_index)} · снимок: ${date(rag.observed_at)}`;
  const cell = (row, value, cls) => { const td = document.createElement('td'); td.textContent = value; if (cls) td.className = cls; row.append(td); return td; };
  $('ragAccounts').replaceChildren();
  data.accounts.filter((a) => a.enabled !== false).forEach((account) => {
    const policy = (rag.loading || []).find((p) => p.account === account.account_id);
    const row = document.createElement('tr');
    cell(row, accountName(account.account_id));
    cell(row, `${(policy?.interval ?? 2).toLocaleString('ru-RU', {maximumFractionDigits: 1})} с`);
    cell(row, policy?.cooldown_until * 1000 > Date.now() ? epoch(policy.cooldown_until) : 'Нет паузы');
    cell(row, epoch(policy?.last_limited));
    cell(row, count(policy?.limits ?? 0));
    $('ragAccounts').append(row);
  });
  $('ragChatSummary').textContent = `${count(rag.ready_accounts)} аккаунтов готовы · ${count(rag.chat_errors)} чатов с ограничениями или ошибками. Лимит чата показан до следующей успешной загрузки.`;
  const mode = $('ragFilter').value;
  const chats = (rag.chats || []).filter((c) => mode === 'errors' ? c.error : mode === 'pending' ? !c.backfill_complete : true);
  $('ragChats').replaceChildren();
  chats.forEach((chat) => {
    const row = document.createElement('tr');
    const title = cell(row, chat.title || chat.chat);
    const subtitle = document.createElement('small'); subtitle.textContent = accountName(chat.account); title.append(subtitle);
    cell(row, chat.backfill_complete ? 'До начала' : chat.last_sync ? 'Загружается' : 'В очереди');
    cell(row, `${count(chat.eligible)} / ${count(chat.indexed)}`);
    cell(row, date(chat.last_sync));
    cell(row, chat.error === 'rate_limited' ? 'Лимит Telegram' : chat.error || 'Без ошибок', chat.error ? 'rag-warning' : '');
    $('ragChats').append(row);
  });
  if (!chats.length) { const row = document.createElement('tr'); const td = cell(row, mode === 'all' ? 'Чаты ещё не обнаружены.' : 'Нет чатов по этому фильтру.'); td.colSpan = 5; $('ragChats').append(row); }
}

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
['historySearch', 'identityFilter', 'actionFilter', 'statusFilter'].forEach((id) => $(id).addEventListener(id === 'historySearch' ? 'input' : 'change', renderHistory));
qa('[data-table-tab]').forEach((button) => button.addEventListener('click', () => { qa('[data-table-tab]').forEach((item) => item.classList.toggle('active', item === button)); const history = button.dataset.tableTab === 'history'; $('historyToolbar').hidden = !history; $('historyTableWrap').hidden = !history; $('usageTableWrap').hidden = history; }));
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
$('ragFilter').onchange = () => renderRag();
if (location.hash === '#rag') navigate('rag');
refresh(); setInterval(refresh, 4000);
