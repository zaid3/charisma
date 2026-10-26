/* Charisma website monitor. Source: https://github.com/zaid3/charisma */
(() => {
  'use strict';
  const script = document.currentScript;
  if (!script || window.Charisma || typeof window.fetch !== 'function' || !/^[A-Za-z0-9_-]{8,80}$/.test(script.dataset.siteKey || '')) return;
  let endpoint;
  try { endpoint = new URL(script.dataset.endpoint || '/ingest', script.src); } catch { return; }
  if (endpoint.protocol !== 'https:' && !(endpoint.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(endpoint.hostname))) return;
  const siteKey = script.dataset.siteKey;
  const page = /^[A-Za-z0-9_-]{1,40}$/.test(script.dataset.page || '') ? script.dataset.page : 'website';
  const knownErrors = new Set(['Error', 'TypeError', 'ReferenceError', 'SyntaxError', 'RangeError', 'URIError', 'EvalError']);
  const sent = new Set();
  const sendRequest = window.fetch.bind(window);
  let stopped = false;
  function report(code, count = 1, error = 'Unknown', file = '', line = 0, column = 0) {
    if (stopped || sent.size >= 30 || count < 1) return;
    const payload = { code, error: knownErrors.has(error) ? error : 'Unknown', file, line, column, count: Math.min(count, 100), page };
    const identity = JSON.stringify(payload);
    if (sent.has(identity)) return;
    sent.add(identity);
    try { sendRequest(endpoint.href, { method: 'POST', credentials: 'omit', cache: 'no-store', keepalive: true,
      headers: { 'Content-Type': 'application/json', 'X-Charisma-Site-Key': siteKey }, body: identity }).catch(() => {}); } catch {}
  }
  function errorName(value) { try { return value && value.name; } catch { return 'Unknown'; } }
  function scriptError(event) {
    let file = '';
    try {
      const url = new URL(event.filename || '', location.origin);
      const basename = url.pathname.split('/').pop();
      if (url.origin === location.origin && /^[A-Za-z0-9_.-]{1,100}$/.test(basename)) file = basename;
    } catch {}
    const number = value => Number.isInteger(value) && value >= 0 && value <= 1000000 ? value : 0;
    report('script-error', 1, errorName(event.error), file, number(event.lineno), number(event.colno));
  }
  function rejected(event) {
    // Never transmit the rejection value, error message, stack or user input.
    report('promise-rejection', 1, errorName(event.reason));
  }
  function visible(element) { return element.getClientRects().length > 0; }
  function scanPage() {
    if (stopped) return;
    if (!document.documentElement.lang.trim()) report('missing-language');
    const images = [...document.querySelectorAll('img:not([alt])')].filter(visible);
    report('missing-alt', images.length);
    const controls = [...document.querySelectorAll('input,select,textarea')].filter(element => {
      if (['hidden', 'submit', 'button', 'reset', 'image'].includes(element.type) || !visible(element)) return false;
      return !(element.labels && element.labels.length) && !element.getAttribute('aria-label') && !element.getAttribute('aria-labelledby') && !element.title;
    });
    report('missing-label', controls.length);
    if (document.documentElement.scrollWidth > document.documentElement.clientWidth + 8) report('horizontal-overflow');
  }
  function stop() {
    stopped = true;
    window.removeEventListener('error', scriptError);
    window.removeEventListener('unhandledrejection', rejected);
    window.removeEventListener('load', scanPage);
  }
  window.addEventListener('error', scriptError);
  window.addEventListener('unhandledrejection', rejected);
  if (document.readyState === 'complete') scanPage();
  else window.addEventListener('load', scanPage, { once: true });
  window.Charisma = Object.freeze({ scan: scanPage, stop });
})();
