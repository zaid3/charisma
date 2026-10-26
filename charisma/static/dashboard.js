(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let token = '', events = [], connected = false, updated = 0, busy = false, generation = 0;
  function status(message, error = false) { $('status').textContent = message; $('status').classList.toggle('error', error); }
  function node(tag, text, className) { const item = document.createElement(tag); if (text !== undefined) item.textContent = String(text); if (className) item.className = className; return item; }
  const date = timestamp => new Date(timestamp * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  function render() {
    $('needs-count').textContent = connected ? events.filter(e => !e.reviewed).length : '—';
    $('runtime-count').textContent = connected ? events.filter(e => e.kind === 'runtime').length : '—';
    $('ux-count').textContent = connected ? events.filter(e => e.kind === 'ux').length : '—';
    const query = $('search').value.toLowerCase();
    const shown = events.filter(e => ($('kind').value === 'all' || e.kind === $('kind').value) &&
      ($('state').value === 'all' || Boolean(e.reviewed) === ($('state').value === 'reviewed')) &&
      [e.title, e.page, e.file].some(value => String(value).toLowerCase().includes(query)));
    $('event-list').replaceChildren();
    $('result-count').textContent = connected ? `${shown.length} of ${events.length} loaded groups` : 'No data loaded';
    $('empty').hidden = shown.length > 0;
    $('empty-title').textContent = !connected ? 'A place for the details.' : events.length ? 'No reports match these filters.' : 'No reports received yet.';
    $('empty-description').textContent = !connected ? 'Connect to view reports from your installed website monitor.' : events.length ? 'Try another category or search term.' : 'Install the monitor and visit your website. No reports does not mean there are no issues.';
    for (const event of shown) {
      const article = node('article', undefined, 'event');
      const detail = node('div');
      const tags = node('div', undefined, 'event-tags');
      tags.append(node('span', event.kind === 'runtime' ? 'Runtime' : 'Experience', `tag ${event.kind}`), node('span', event.reviewed ? 'Reviewed' : 'Needs review', `tag ${event.reviewed ? 'reviewed' : ''}`));
      detail.append(tags, node('h3', event.title), node('p', [event.page, event.file ? `${event.file}:${event.line}` : '', event.error !== 'Unknown' ? event.error : ''].filter(Boolean).join(' · ')));
      const meta = node('div', undefined, 'event-meta');
      meta.append(node('p', `${event.count.toLocaleString()} reported · ${date(event.last_seen)}`));
      if (!event.reviewed) {
        const button = node('button', 'Mark reviewed', 'secondary');
        button.setAttribute('aria-label', `Mark reviewed: ${event.title} on ${event.page}`);
        button.addEventListener('click', async () => {
          const current = generation;
          button.disabled = true;
          try {
            await api(`/api/events/${event.id}/review`, 'POST');
            if (current === generation) { await refresh(); $('status').focus({ preventScroll: true }); }
          } catch (error) { if (current === generation) { status(error.message, true); button.disabled = false; } }
        });
        meta.append(button);
      } else meta.append(node('span', 'Acknowledged', 'reviewed'));
      article.append(detail, meta); $('event-list').append(article);
    }
  }
  async function api(path, method = 'GET') {
    const response = await fetch(path, { method, headers: { Authorization: `Bearer ${token}` }, credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!response.ok) throw new Error(response.status === 401 ? 'The access token was not accepted. Disconnect and enter the correct token.' : 'Reports could not be loaded. Check the server and try again.');
    return response.json();
  }
  let pendingUndo = null;
  function renderRuns(result) {
    $('history-status').textContent = result.message;
    $('run-list').replaceChildren();
    for (const run of result.runs) {
      const article = node('article', undefined, 'event run');
      const details = node('details');
      details.append(node('summary', `${run.project} · ${run.commit_sha.slice(0, 8)}`));
      const timeline = node('ol', undefined, 'timeline');
      for (const step of run.timeline) {
        const item = node('li');
        item.append(node('strong', `${step.role.replaceAll('_', ' ')}: ${step.status.replaceAll('_', ' ')}`), node('time', date(step.at)), node('p', step.detail || ''));
        timeline.append(item);
      }
      details.append(timeline);
      const actions = node('div', undefined, 'actions');
      const pause = node('button', run.paused ? 'Resume repairs' : 'Pause repairs', 'secondary');
      pause.addEventListener('click', () => control(run.id, run.paused ? 'resume' : 'pause', pause));
      actions.append(pause);
      if (run.can_undo) {
        const undo = node('button', 'Undo candidate', 'secondary');
        undo.addEventListener('click', () => { pendingUndo = run.id; $('undo-dialog').showModal(); $('undo-cancel').focus(); });
        actions.append(undo);
      }
      article.append(node('h3', run.project), node('span', `${run.status.replaceAll('_', ' ')}${run.paused ? ' · repairs paused' : ''}`, 'run-status'), node('p', `Updated ${date(run.updated)}`), node('p', run.detail || '', 'run-detail'), details, actions);
      $('run-list').append(article);
    }
  }
  async function control(id, action, button) {
    const current = generation;
    button.disabled = true;
    try {
      const response = await fetch(`/api/runs/${id}/${action}`, {method:'POST', headers:{Authorization:`Bearer ${token}`}, credentials:'omit', signal:AbortSignal.timeout(10000)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'The action was not completed.');
      if (current === generation) await refresh();
    } catch (error) { if (current === generation) status(error.message, true); }
    finally { button.disabled = false; }
  }
  $('undo-cancel').addEventListener('click', () => { pendingUndo = null; $('undo-dialog').close(); });
  $('undo-confirm').addEventListener('click', () => { const id = pendingUndo; pendingUndo = null; $('undo-dialog').close(); if (id) control(id, 'undo', $('undo-confirm')); });
  async function refresh() {
    if (busy) return;
    const current = generation;
    busy = true; $('refresh').disabled = true; $('connect').disabled = true;
    status('Loading reports…');
    try {
      const result = await api('/api/events');
      if (current !== generation) return;
      events = result.events; updated = result.updated_at; connected = true;
      $('connect-panel').hidden = true; $('disconnect').hidden = false;
      $('connection').textContent = 'Connected'; $('connection').className = 'connection connected';
      status(`Updated ${date(updated)}. Counts describe the ${events.length} loaded report groups.`);
      render();
      try { const history = await api('/api/runs'); if (current === generation) renderRuns(history); }
      catch { if (current === generation) $('history-status').textContent = 'Worker history could not be loaded. Refresh to retry.'; }
    } catch (error) {
      if (current === generation) {
        status(error.name === 'TimeoutError' ? 'The server took too long to respond. Try refreshing.' : error.message, true);
        $('connection').textContent = connected ? 'Refresh failed' : 'Disconnected';
        $('connection').className = 'connection stale';
      }
    } finally {
      if (current === generation) { busy = false; $('connect').disabled = false; $('refresh').disabled = !connected; }
    }
  }
  $('status').setAttribute('tabindex', '-1');
  $('connect-form').addEventListener('submit', event => { event.preventDefault(); token = $('token').value; $('token').value = ''; refresh(); });
  $('refresh').addEventListener('click', refresh);
  $('disconnect').addEventListener('click', () => {
    $('run-list').replaceChildren(); $('history-status').textContent = 'Connect to view the worker history.'; pendingUndo = null; if ($('undo-dialog').open) $('undo-dialog').close();
    generation++; token = ''; events = []; connected = false; busy = false; updated = 0;
    $('connection').textContent = 'Disconnected'; $('connection').className = 'connection';
    $('connect-panel').hidden = false; $('disconnect').hidden = true; $('refresh').disabled = true; $('connect').disabled = false;
    status('Disconnected. The access token and reports have been cleared from this tab.'); render(); $('token').focus();
  });
  for (const id of ['search', 'kind', 'state']) $(id).addEventListener('input', render);
  setInterval(() => { if (connected && updated && Date.now() / 1000 - updated > 120) { $('connection').textContent = 'Refresh to update'; $('connection').className = 'connection stale'; } }, 15000);
})();
