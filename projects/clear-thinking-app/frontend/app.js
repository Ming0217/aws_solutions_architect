/*
 * Clear Thinking — cloud layer.
 *
 * Layers on top of the inline script in index.html (which owns the stage UI,
 * the memo generator, and localStorage). This file adds:
 *   - Cognito Hosted UI sign-in (Authorization Code + PKCE, public client)
 *   - Cloud persistence of decisions via the CRUD API (list / open / save / delete)
 *   - The four AI assists, streamed from the AI Lambda Function URL
 *
 * Config (API/AI URLs, Cognito domain + client id) is fetched at runtime from
 * config.json, which CDK generates at deploy time. Nothing is hardcoded.
 *
 * It reuses globals defined by the inline script: `state`, `saveState()`,
 * `openStage()`, `updateProgress()`.
 */
(function () {
  'use strict';

  let CONFIG = null;
  let currentId = null;
  let saveTimer = null;

  // ---- token storage -----------------------------------------------------
  const TOKENS_KEY = 'ct_tokens';
  const getTokens = () => {
    try { return JSON.parse(sessionStorage.getItem(TOKENS_KEY) || 'null'); } catch { return null; }
  };
  const storeTokens = (t) => {
    const prev = getTokens() || {};
    const tokens = {
      access_token: t.access_token || prev.access_token,
      id_token: t.id_token || prev.id_token,
      refresh_token: t.refresh_token || prev.refresh_token,
      expiresAt: Date.now() + (t.expires_in ? t.expires_in * 1000 : 3600 * 1000),
    };
    sessionStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
  };
  const clearTokens = () => sessionStorage.removeItem(TOKENS_KEY);

  // ---- small helpers -----------------------------------------------------
  function b64url(bytes) {
    let s = btoa(String.fromCharCode.apply(null, new Uint8Array(bytes)));
    return s.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function randomString(n) {
    const a = new Uint8Array(n);
    crypto.getRandomValues(a);
    return b64url(a);
  }
  async function pkceChallenge(verifier) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    return b64url(digest);
  }
  function decodeJwt(token) {
    try {
      const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      return JSON.parse(decodeURIComponent(escape(atob(part))));
    } catch { return {}; }
  }
  const redirectUri = () => window.location.origin + '/';

  // ---- auth flow ---------------------------------------------------------
  async function ctSignIn() {
    if (!CONFIG) { alert('Backend not configured yet.'); return; }
    const verifier = randomString(32);
    const challenge = await pkceChallenge(verifier);
    const st = randomString(16);
    sessionStorage.setItem('ct_pkce', verifier);
    sessionStorage.setItem('ct_state', st);
    const url =
      CONFIG.cognitoDomain +
      '/oauth2/authorize?response_type=code' +
      '&client_id=' + encodeURIComponent(CONFIG.clientId) +
      '&redirect_uri=' + encodeURIComponent(redirectUri()) +
      '&scope=' + encodeURIComponent('openid email profile') +
      '&state=' + st +
      '&code_challenge=' + challenge +
      '&code_challenge_method=S256';
    window.location.assign(url);
  }

  function ctSignOut() {
    clearTokens();
    currentId = null;
    sessionStorage.removeItem('ct_current_id');
    if (!CONFIG) { updateAuthUi(); return; }
    window.location.assign(
      CONFIG.cognitoDomain + '/logout?client_id=' + encodeURIComponent(CONFIG.clientId) +
      '&logout_uri=' + encodeURIComponent(redirectUri()),
    );
  }

  async function exchangeCode(code) {
    const verifier = sessionStorage.getItem('ct_pkce') || '';
    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: CONFIG.clientId,
      code,
      redirect_uri: redirectUri(),
      code_verifier: verifier,
    });
    const resp = await fetch(CONFIG.cognitoDomain + '/oauth2/token', {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body,
    });
    if (resp.ok) storeTokens(await resp.json());
  }

  async function refreshTokens(rt) {
    const body = new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: CONFIG.clientId,
      refresh_token: rt,
    });
    const resp = await fetch(CONFIG.cognitoDomain + '/oauth2/token', {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body,
    });
    if (!resp.ok) { clearTokens(); return false; }
    storeTokens(await resp.json());
    return true;
  }

  async function getAccessToken() {
    const tk = getTokens();
    if (!tk) return null;
    if (Date.now() < tk.expiresAt - 30000) return tk.access_token;
    if (tk.refresh_token && (await refreshTokens(tk.refresh_token))) return getTokens().access_token;
    clearTokens();
    return null;
  }

  const isSignedIn = () => !!getTokens();

  // ---- CRUD API ----------------------------------------------------------
  async function api(method, path, payload) {
    const token = await getAccessToken();
    if (!token) { updateAuthUi(); throw new Error('not signed in'); }
    const resp = await fetch(CONFIG.apiUrl + path, {
      method,
      headers: {
        authorization: 'Bearer ' + token,
        ...(payload ? { 'content-type': 'application/json' } : {}),
      },
      body: payload ? JSON.stringify(payload) : undefined,
    });
    if (resp.status === 204) return null;
    if (!resp.ok) throw new Error('API ' + resp.status);
    return resp.json();
  }
  const apiList = () => api('GET', '/decisions');
  const apiCreate = (d) => api('POST', '/decisions', d);
  const apiGet = (id) => api('GET', '/decisions/' + id);
  const apiUpdate = (id, d) => api('PUT', '/decisions/' + id, d);
  const apiDelete = (id) => api('DELETE', '/decisions/' + id);

  // ---- decision helpers --------------------------------------------------
  function deriveTitle() {
    const p = (state.fields && state.fields['s1-problem']) ? String(state.fields['s1-problem']).trim() : '';
    if (p) return p.length > 60 ? p.slice(0, 57) + '…' : p;
    return 'Untitled decision';
  }

  function applyStateToDom() {
    document.querySelectorAll('[data-field]').forEach((el) => {
      el.value = (state.fields && state.fields[el.dataset.field]) || '';
    });
    document.querySelectorAll('.check-box').forEach((cb) => {
      cb.checked = !!(state.fields && state.fields[cb.id]);
    });
    document.querySelectorAll('.stage').forEach((s) => {
      const idx = parseInt(s.dataset.stage, 10);
      const done = Array.isArray(state.completed) && state.completed.includes(idx);
      s.classList.toggle('completed', done);
      const btn = s.querySelector('.btn-complete');
      if (btn) {
        btn.textContent = done ? 'Undo Complete' : 'Complete & Continue';
        btn.classList.toggle('btn-complete-done', done);
        btn.classList.toggle('btn-primary', !done);
      }
    });
    if (typeof updateProgress === 'function') updateProgress();
  }

  function setCurrent(id) {
    currentId = id;
    if (id) sessionStorage.setItem('ct_current_id', id);
    else sessionStorage.removeItem('ct_current_id');
    const del = document.getElementById('btn-delete-decision');
    if (del) del.style.display = id ? '' : 'none';
    const sel = document.getElementById('decisions-select');
    if (sel && id) sel.value = id;
  }

  async function refreshList() {
    try {
      const res = await apiList();
      const items = (res && res.items) || [];
      const sel = document.getElementById('decisions-select');
      if (!sel) return;
      sel.innerHTML = '<option value="">Your decisions…</option>';
      items
        .sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''))
        .forEach((it) => {
          const opt = document.createElement('option');
          opt.value = it.decisionId;
          opt.textContent = it.title || 'Untitled decision';
          sel.appendChild(opt);
        });
      if (currentId) sel.value = currentId;
    } catch (e) { /* not signed in / offline */ }
  }

  async function ctNewDecision() {
    if (!isSignedIn()) return ctSignIn();
    try {
      const item = await apiCreate({ title: 'Untitled decision', fields: {}, completed: [] });
      state.fields = {};
      state.completed = [];
      if (typeof saveState === 'function') saveState();
      applyStateToDom();
      setCurrent(item.decisionId);
      await refreshList();
      if (typeof openStage === 'function') openStage(0);
      setStatus('New decision created');
    } catch (e) { setStatus('Could not create decision'); }
  }

  async function ctOpenDecision(id) {
    if (!id) return;
    if (!isSignedIn()) return ctSignIn();
    try {
      const item = await apiGet(id);
      state.fields = item.fields || {};
      state.completed = Array.isArray(item.completed) ? item.completed : [];
      if (typeof saveState === 'function') saveState();
      applyStateToDom();
      setCurrent(id);
      setStatus('Opened');
    } catch (e) { setStatus('Could not open decision'); }
  }

  async function ctDeleteCurrent() {
    if (!currentId) return;
    if (!confirm('Delete this decision permanently? This cannot be undone.')) return;
    try {
      await apiDelete(currentId);
      setCurrent(null);
      await refreshList();
      setStatus('Deleted');
    } catch (e) { setStatus('Could not delete'); }
  }

  // debounced cloud save of the current decision
  function scheduleSave() {
    if (!isSignedIn() || !currentId) return;
    setStatus('Saving…');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      try {
        await apiUpdate(currentId, {
          title: deriveTitle(),
          fields: state.fields || {},
          completed: state.completed || [],
        });
        setStatus('Saved');
        // keep the dropdown label in sync with the (possibly new) title
        const sel = document.getElementById('decisions-select');
        const opt = sel && sel.querySelector('option[value="' + currentId + '"]');
        if (opt) opt.textContent = deriveTitle();
      } catch (e) { setStatus('Save failed'); }
    }, 1000);
  }

  function setStatus(msg) {
    const el = document.getElementById('sync-status');
    if (el) el.textContent = msg;
  }

  // ---- AI assists --------------------------------------------------------
  function f(k) {
    return state.fields && state.fields[k] ? String(state.fields[k]).trim() : '';
  }

  function buildDecisionInput() {
    const options = [];
    [['A', 's2-opt-a'], ['B', 's2-opt-b'], ['C', 's2-opt-c']].forEach(([label, key]) => {
      const desc = f(key);
      if (desc) options.push({ label: 'Option ' + label, description: desc, pros: f(key + '-pro'), cons: f(key + '-con') });
    });
    if (f('s2-do-nothing')) options.push({ label: 'Do nothing', description: f('s2-do-nothing') });
    if (f('s2-hybrid')) options.push({ label: 'Hybrid', description: f('s2-hybrid') });

    const evidence = [
      ['Facts', f('s1-facts')],
      ['Assumptions', f('s1-assumptions')],
      ['Unknowns', f('s1-unknowns')],
      ['Criteria (ranked)', f('s3-criteria')],
      ['Base rate / reference class', f('s3-base-rate')],
      ['Expert input', f('s3-expert')],
      ['Confidence', f('s3-confidence')],
    ]
      .filter(([, v]) => v)
      .map(([k, v]) => k + ':\n' + v)
      .join('\n\n');

    const problemParts = [f('s1-problem')];
    if (f('s1-root-cause')) problemParts.push('Root cause: ' + f('s1-root-cause'));
    if (f('s1-why-now')) problemParts.push('Why now: ' + f('s1-why-now'));

    return {
      title: deriveTitle(),
      problem: problemParts.filter(Boolean).join('\n'),
      options,
      evidence,
      leaningOption: f('s4-decision'),
      decision: f('s4-decision'),
    };
  }

  async function ctRunAssist(btn) {
    if (!isSignedIn()) return ctSignIn();
    const assist = btn.dataset.assist;
    const out = document.getElementById(btn.dataset.out);
    const token = await getAccessToken();
    if (!token) { updateAuthUi(); return; }

    const panelBtns = btn.parentElement.querySelectorAll('button');
    panelBtns.forEach((b) => (b.disabled = true));
    out.classList.add('visible');
    out.textContent = 'Thinking…';

    try {
      const resp = await fetch(CONFIG.aiUrl, {
        method: 'POST',
        headers: { authorization: 'Bearer ' + token, 'content-type': 'application/json' },
        body: JSON.stringify({ assist, decision: buildDecisionInput() }),
      });
      if (!resp.ok || !resp.body) {
        const t = await resp.text().catch(() => '');
        out.textContent = 'The assist could not run (' + resp.status + '). ' + t;
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      out.textContent = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        out.textContent += decoder.decode(value, { stream: true });
        out.scrollTop = out.scrollHeight;
      }
    } catch (e) {
      out.textContent = 'Network error running the assist. Please try again.';
    } finally {
      panelBtns.forEach((b) => (b.disabled = false));
    }
  }

  // ---- UI state ----------------------------------------------------------
  function updateAuthUi() {
    const signedIn = isSignedIn();
    const tk = getTokens();
    const email = tk && tk.id_token ? decodeJwt(tk.id_token).email : '';
    const show = (id, on) => { const el = document.getElementById(id); if (el) el.style.display = on ? '' : 'none'; };

    show('btn-signin', !signedIn && !!CONFIG);
    show('btn-signout', signedIn);
    show('decisions-bar', signedIn);
    show('signin-prompt', !signedIn && !!CONFIG);
    const emailEl = document.getElementById('auth-email');
    if (emailEl) emailEl.textContent = email || '';
    if (!currentId) {
      const del = document.getElementById('btn-delete-decision');
      if (del) del.style.display = 'none';
    }
  }

  // ---- init --------------------------------------------------------------
  async function init() {
    try {
      const resp = await fetch('config.json', { cache: 'no-store' });
      if (resp.ok) CONFIG = await resp.json();
    } catch { /* running without a deployed backend */ }

    // Wire cloud autosave onto the existing form inputs.
    document.querySelectorAll('[data-field]').forEach((el) => el.addEventListener('input', scheduleSave));
    document.querySelectorAll('.check-box').forEach((cb) => cb.addEventListener('change', scheduleSave));
    document.querySelectorAll('.btn-complete').forEach((b) => b.addEventListener('click', scheduleSave));

    if (CONFIG) {
      const params = new URLSearchParams(window.location.search);
      if (params.get('code') && params.get('state')) {
        if (params.get('state') === sessionStorage.getItem('ct_state')) {
          await exchangeCode(params.get('code'));
        }
        window.history.replaceState({}, '', window.location.pathname);
      }
    }

    updateAuthUi();

    if (isSignedIn()) {
      await refreshList();
      const saved = sessionStorage.getItem('ct_current_id');
      if (saved) await ctOpenDecision(saved);
    }
  }

  // Expose the handlers referenced by inline onclick attributes.
  window.ctSignIn = ctSignIn;
  window.ctSignOut = ctSignOut;
  window.ctNewDecision = ctNewDecision;
  window.ctOpenDecision = ctOpenDecision;
  window.ctDeleteCurrent = ctDeleteCurrent;
  window.ctRunAssist = ctRunAssist;

  // The inline script restores localStorage on DOMContentLoaded; run init after
  // so a freshly-opened cloud decision (if any) wins.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
