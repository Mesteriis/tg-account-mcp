/* Pure table selection shared by the dashboard and its regression checks. */
(function (root) {
  'use strict';
  function paginate(rows, page = 1, size = 10) {
    size = [10, 25, 50, 100].includes(Number(size)) ? Number(size) : 10;
    const pages = Math.max(1, Math.ceil(rows.length / size));
    page = Math.min(pages, Math.max(1, Number.isFinite(Number(page)) ? Math.floor(Number(page)) : 1));
    return {items: rows.slice((page - 1) * size, page * size), page, size, pages, total: rows.length, start: rows.length ? (page - 1) * size + 1 : 0, end: Math.min(page * size, rows.length)};
  }
  function stateOf(chat) {
    if (chat.accountEnabled === false) return 'account_off';
    if (!chat.enabled) return 'paused';
    if (!chat.rag_enabled && !chat.s3_enabled) return 'off';
    if ((!chat.rag_enabled || chat.ragRunning === false) && (!chat.s3_enabled || chat.mediaRunning === false)) return 'paused';
    if (chat.error || chat.media_errors) return 'error';
    if (chat.rag_enabled && (chat.indexed == null || chat.eligible == null || chat.indexed < chat.eligible || !chat.backfill_complete)) return 'pending';
    if (chat.s3_enabled && (chat.media_pending || !chat.mediaConfigured)) return 'pending';
    return 'ready';
  }
  function selectChats(rows, filters = {}) {
    const query = (filters.query || '').trim().toLocaleLowerCase('ru');
    const priority = {error: 0, pending: 1, ready: 2, off: 3, paused: 4, account_off: 5};
    return rows.filter(c => (!query || `${c.title} ${c.chat} ${c.accountName}`.toLocaleLowerCase('ru').includes(query))
      && (!filters.account || c.account === filters.account)
      && (!filters.kind || c.kind === filters.kind)
      && (!filters.state || (filters.state === 'off' ? ['off', 'paused', 'account_off'].includes(stateOf(c)) : stateOf(c) === filters.state))
      && (!filters.rule || (filters.rule === 'fixed' ? c.kind === 'private' : c.kind !== 'private' && (filters.rule === 'own' ? !c.inherited : c.inherited)))
      && (!filters.s3 || Boolean(c.s3_enabled) === (filters.s3 === 'on')))
      .sort((a, b) => {
        let delta = 0;
        if (filters.sort === 'pending') delta = ((b.eligible || 0) - (b.indexed || 0)) - ((a.eligible || 0) - (a.indexed || 0));
        else if (filters.sort === 'recent') delta = (Date.parse(b.last_sync) || 0) - (Date.parse(a.last_sync) || 0);
        else if (filters.sort !== 'title') delta = priority[stateOf(a)] - priority[stateOf(b)];
        const result = delta || String(a.title || a.chat).localeCompare(String(b.title || b.chat), 'ru', {numeric: true}) || `${a.account}:${a.chat}`.localeCompare(`${b.account}:${b.chat}`);
        return filters.reverse ? -result : result;
      });
  }
  const api = {paginate, stateOf, selectChats};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.TgTables = api;
})(globalThis);
