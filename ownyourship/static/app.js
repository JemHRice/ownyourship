'use strict';

// ── State ────────────────────────────────────────────────────────────────────

const S = {
  mode: 'easy',
  sessionId: null,
  currentQuestion: null,
  questionCount: 0,
  correctCount: 0,
  totalBlocks: 0,
  answeredCount: 0,
  scanComplete: false,
  costWarningShown: false,
  achievementShown: false,
  wrongAttempts: 0,
};

// ── DOM helpers ──────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const hide = el => el.classList.add('hidden');
const show = el => el.classList.remove('hidden');

function showScreen(name) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const el = $(`screen-${name}`);
  if (el) el.classList.add('active');
}

function setNavActive(name) {
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  $(`nav-${name}`)?.classList.add('active');
}

// ── API helpers ──────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

const GET  = path        => api('GET',  path);
const POST = (path, body) => api('POST', path, body);

// ── Boot ─────────────────────────────────────────────────────────────────────

async function boot() {
  await pollUntilReady();
}

async function pollUntilReady() {
  showScreen('scanning');
  $('nav-quiz').classList.add('active');

  // Trigger initial scan
  await POST('/api/scan').catch(() => {});

  const status = await waitForScan();
  S.scanComplete = true;
  S.totalBlocks = status.total_blocks;

  $('proj-name').textContent = status.project_name;
  $('proj-meta').textContent = `${status.project_path}`;
  $('welcome-subtitle').textContent =
    `${status.total_blocks} quizzable block${status.total_blocks !== 1 ? 's' : ''} found`;

  $('btn-start').disabled = status.total_blocks === 0;
  if (status.total_blocks === 0) {
    $('welcome-subtitle').textContent = 'No quizzable blocks found. Check .oys/config.json.';
  }

  showScreen('welcome');
}

async function waitForScan() {
  while (true) {
    const st = await GET('/api/status');
    if (st.scan_error) throw new Error(st.scan_error);
    if (st.scan_complete) return st;
    await sleep(800);
  }
}

// ── Mode selection ───────────────────────────────────────────────────────────

document.querySelectorAll('.mode-card').forEach(card => {
  card.addEventListener('click', () => {
    document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
    S.mode = card.dataset.mode;
  });
});

// ── Start quiz ───────────────────────────────────────────────────────────────

$('btn-start').addEventListener('click', startQuiz);

async function startQuiz() {
  $('btn-start').disabled = true;
  try {
    const sess = await POST('/api/session/start', { mode: S.mode });
    S.sessionId = sess.session_id;
    S.questionCount = 0;
    S.correctCount = 0;
    S.answeredCount = 0;
    S.costWarningShown = false;
    S.achievementShown = false;
    $('q-mode-badge').textContent = capitalise(S.mode);
    setNavActive('quiz');
    showScreen('quiz');
    await loadNextQuestion();
  } catch (e) {
    alert('Could not start session: ' + e.message);
    $('btn-start').disabled = false;
  }
}

// ── Question loading ─────────────────────────────────────────────────────────

const MAX_QUESTIONS_PER_SESSION = 20;

async function loadNextQuestion() {
  if (S.questionCount >= MAX_QUESTIONS_PER_SESSION) {
    await endSession();
    showSessionDone(`${MAX_QUESTIONS_PER_SESSION}-question session complete!`);
    return;
  }

  S.wrongAttempts = 0;
  clearFeedback();
  hide($('code-snippet-wrap'));
  hide($('try-again-msg'));
  $('q-text').textContent = 'Loading question...';
  hide($('mc-options'));

  try {
    const q = await GET(`/api/question?session_id=${S.sessionId}&mode=${S.mode}`);

    if (q.finished) {
      await endSession();
      showSessionDone('You answered all available questions this session!');
      return;
    }

    S.currentQuestion = q;
    S.answeredCount = q.answered_count ?? S.answeredCount;
    S.totalBlocks = q.total_blocks ?? S.totalBlocks;

    updateQuizHeader(q);
    handleCostWarning(q);

    $('q-text').textContent = q.question;
    renderCodeSnippet(q.code_snippet);
    renderMC(q.options);
  } catch (e) {
    $('q-text').textContent = 'Error loading question: ' + e.message;
  }
}

function updateQuizHeader(q) {
  S.questionCount++;
  $('q-mode-badge').textContent = capitalise(S.mode);
  $('q-file-badge').textContent = q.file_path || '';
  $('q-counter').textContent = `Q${S.questionCount}`;
  $('q-score').textContent = S.questionCount > 1
    ? `${S.correctCount}/${S.questionCount - 1} correct`
    : '';
  updateCostBadge(q.session_cost_usd, q.cost_warning);
  updateProgressBar();
}

function updateCostBadge(cost, warn) {
  const badge = $('q-cost-badge');
  badge.textContent = `~$${cost.toFixed(4)}`;
  badge.classList.toggle('warn', warn);
}

function updateProgressBar() {
  // progress shown in stats — update live if on stats screen
  if (S.totalBlocks > 0) {
    const pct = Math.round(S.answeredCount / S.totalBlocks * 100);
    // update footer progress if we add one later
  }
}

function handleCostWarning(q) {
  if (q.cost_warning && !S.costWarningShown) {
    S.costWarningShown = true;
    $('cost-toast').classList.add('show');
    setTimeout(() => $('cost-toast').classList.remove('show'), 7000);
  }
}

// ── Code snippet rendering ───────────────────────────────────────────────────

function renderCodeSnippet(snippet) {
  if (!snippet) { hide($('code-snippet-wrap')); return; }
  const lines = snippet.split('\n').map(line => {
    const isTarget = line.startsWith('>');
    const escaped = escapeHtml(line);
    return isTarget
      ? `<span class="snippet-target-line">${escaped}</span>`
      : `<span class="snippet-ctx-line">${escaped}</span>`;
  });
  $('code-snippet').innerHTML = lines.join('\n');
  show($('code-snippet-wrap'));
}

// ── Multiple choice rendering ────────────────────────────────────────────────

function renderMC(options) {
  const container = $('mc-options');
  container.innerHTML = '';
  show(container);

  const labels = ['A', 'B', 'C', 'D'];
  options.forEach((opt, i) => {
    const btn = document.createElement('button');
    btn.className = 'mc-option';
    btn.innerHTML = `<span class="mc-label">${labels[i]}</span><span>${escapeHtml(stripLabel(opt))}</span>`;
    btn.dataset.letter = labels[i];
    btn.addEventListener('click', () => handleMCAnswer(labels[i]));
    container.appendChild(btn);
  });
}

function stripLabel(opt) {
  // Remove "A: " or "A. " prefix if present
  return opt.replace(/^[A-D][:.]\s*/, '');
}

async function handleMCAnswer(letter) {
  const q = S.currentQuestion;
  const correct = q.correct_answer?.toUpperCase()?.charAt(0);
  const isCorrect = letter === correct;

  // Mark clicked option immediately
  document.querySelectorAll('.mc-option').forEach(btn => {
    if (btn.dataset.letter === letter) {
      btn.classList.add(isCorrect ? 'correct' : 'wrong');
      btn.disabled = true;
    }
  });

  if (isCorrect) {
    disableMCOptions();
    hide($('try-again-msg'));
    await submitAnswer(letter);
  } else {
    S.wrongAttempts++;
    if (S.wrongAttempts >= 2) {
      // Used both attempts — reveal correct answer and submit
      disableMCOptions();
      document.querySelectorAll('.mc-option').forEach(btn => {
        if (btn.dataset.letter === correct) btn.classList.add('revealed');
      });
      hide($('try-again-msg'));
      await submitAnswer(letter);
    } else {
      // First wrong attempt — let them try again
      show($('try-again-msg'));
    }
  }
}

function disableMCOptions() {
  document.querySelectorAll('.mc-option').forEach(b => b.disabled = true);
}

// ── Answer submission ────────────────────────────────────────────────────────

async function submitAnswer(userAnswer) {
  const q = S.currentQuestion;
  try {
    const result = await POST('/api/answer', {
      session_id: S.sessionId,
      block_id: q.block_id,
      mode: S.mode,
      question_text: q.question,
      question_type: q.type,
      user_answer: userAnswer,
      correct_answer: q.correct_answer,
      explanation: q.explanation || '',
    });

    if (result.is_correct) S.correctCount++;
    updateCostBadge(result.session_cost_usd, result.cost_warning);
    showFeedback(result);
    checkAchievement();
  } catch (e) {
    showFeedbackError(e.message);
  }
}

// ── Feedback display ─────────────────────────────────────────────────────────

function showFeedback(result) {
  const card = $('feedback-card');
  card.style.display = '';
  card.className = result.is_correct ? 'correct-fb show' : 'wrong-fb show';
  $('fb-icon').textContent  = result.is_correct ? '✓' : '✗';
  $('fb-title').textContent = result.is_correct ? 'Correct!' : 'Not quite';
  $('fb-title').style.color = result.is_correct ? 'var(--success)' : 'var(--danger)';
  $('fb-text').textContent  = result.feedback || '';
  $('fb-explanation').textContent = result.explanation
    ? `Explanation: ${result.explanation}`
    : '';
}

function showFeedbackError(msg) {
  const card = $('feedback-card');
  card.style.display = '';
  card.className = 'wrong-fb show';
  $('fb-icon').textContent  = '!';
  $('fb-title').textContent = 'Error';
  $('fb-title').style.color = 'var(--danger)';
  $('fb-text').textContent  = msg;
  $('fb-explanation').textContent = '';
}

function clearFeedback() {
  const card = $('feedback-card');
  card.className = '';
  card.style.display = '';  // clear inline style so CSS takes over (display:none by default)
}

// ── Next question ────────────────────────────────────────────────────────────

$('btn-next').addEventListener('click', loadNextQuestion);
$('btn-see-stats').addEventListener('click', openStats);

// ── Achievement check ────────────────────────────────────────────────────────

async function checkAchievement() {
  if (S.achievementShown) return;
  try {
    const stats = await GET('/api/stats');
    if (stats.has_95_achievement) {
      S.achievementShown = true;
      $('achievement-overlay').classList.add('show');
    }
  } catch (_) {}
}

$('btn-achievement-close').addEventListener('click', () => {
  $('achievement-overlay').classList.remove('show');
});

// ── Stats & tabs ─────────────────────────────────────────────────────────────

async function openStats() {
  setNavActive('stats');
  showScreen('stats');
  activateTab('overview');
  await loadStats();
}

function activateTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === name);
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('hidden', p.id !== `tab-${name}`);
  });
}

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const tab = btn.dataset.tab;
    activateTab(tab);
    if (tab === 'history') await loadHistory();
  });
});

async function loadStats() {
  try {
    const stats = await GET('/api/stats');
    if (stats.error) return;
    renderStats(stats);
  } catch (e) {
    console.error('Stats load error:', e);
  }
}

function renderStats(stats) {
  const pct = stats.coverage_pct ?? 0;
  const pctEl = $('stats-pct');
  pctEl.textContent = `${pct}%`;
  pctEl.className = 'coverage-pct' + (pct >= 95 ? ' full' : '');

  const bar = $('stats-pct-bar');
  bar.style.width = `${pct}%`;
  bar.className = 'progress-fill' + (pct >= 95 ? ' high' : pct < 40 ? ' warn' : '');

  const ach = $('achievement-banner-inline');
  if (stats.has_95_achievement) show(ach); else hide(ach);

  // Files
  const fb = $('file-tbody');
  fb.innerHTML = '';
  (stats.file_stats || []).forEach(f => {
    const p = f.total_blocks ? Math.round(f.correct_blocks / f.total_blocks * 100) : 0;
    fb.insertAdjacentHTML('beforeend', `
      <tr>
        <td style="font-family:var(--font-mono);font-size:12px">${escapeHtml(f.file_path)}</td>
        <td>${f.total_blocks}</td>
        <td>
          <div class="pct-cell">
            <div class="mini-bar"><div class="mini-fill${p >= 95 ? ' full' : ''}" style="width:${p}%"></div></div>
            <span style="min-width:38px;text-align:right">${p}%</span>
          </div>
        </td>
      </tr>`);
  });

  // Concepts
  const cb = $('concept-tbody');
  cb.innerHTML = '';
  (stats.concept_stats || []).forEach(c => {
    const p = c.total_blocks ? Math.round(c.correct_blocks / c.total_blocks * 100) : 0;
    cb.insertAdjacentHTML('beforeend', `
      <tr>
        <td>${capitalise(c.block_type)}</td>
        <td>${c.total_blocks}</td>
        <td>${c.correct_blocks}</td>
        <td>
          <div class="pct-cell">
            <div class="mini-bar"><div class="mini-fill${p >= 95 ? ' full' : ''}" style="width:${p}%"></div></div>
            <span style="min-width:38px;text-align:right">${p}%</span>
          </div>
        </td>
      </tr>`);
  });

  // Sessions
  const sb = $('session-tbody');
  sb.innerHTML = '';
  (stats.sessions || []).forEach(s => {
    const score = s.questions_answered
      ? `${s.correct_answers}/${s.questions_answered}`
      : '—';
    const cost = s.cost_usd != null ? `$${Number(s.cost_usd).toFixed(4)}` : '—';
    const date = s.started_at ? new Date(s.started_at + 'Z').toLocaleString() : '—';
    sb.insertAdjacentHTML('beforeend', `
      <tr>
        <td style="font-size:12px">${date}</td>
        <td>${capitalise(s.mode)}</td>
        <td>${s.questions_answered}</td>
        <td>${score}</td>
        <td>${cost}</td>
      </tr>`);
  });
}

// ── History ──────────────────────────────────────────────────────────────────

async function loadHistory() {
  const container = $('history-content');
  container.innerHTML = '<p class="text-muted" style="padding:16px 0">Loading...</p>';
  try {
    const sessions = await GET('/api/history');
    renderHistory(sessions);
  } catch (e) {
    container.innerHTML = `<p class="text-muted">Failed to load history: ${escapeHtml(e.message)}</p>`;
  }
}

function renderHistory(sessions) {
  const container = $('history-content');
  if (!sessions.length) {
    container.innerHTML = '<p class="text-muted" style="padding:16px 0">No sessions recorded yet.</p>';
    return;
  }

  container.innerHTML = sessions.map(session => {
    const date = session.started_at
      ? new Date(session.started_at + 'Z').toLocaleString() : '—';
    const score = `${session.correct_answers} / ${session.total_questions} correct`;
    const cost  = `$${Number(session.cost_usd || 0).toFixed(4)}`;

    const qHtml = (session.questions || []).map(q => {
      const resultClass = q.is_correct ? 'hq-correct' : 'hq-wrong';
      const resultIcon  = q.is_correct ? '✓' : '✗';
      const wrongAnswer = !q.is_correct
        ? `<div class="hq-correct-ans">Correct answer: <strong>${escapeHtml(q.correct_answer || '—')}</strong></div>`
        : '';
      const feedbackHtml = q.feedback
        ? `<div class="hq-feedback">${escapeHtml(q.feedback)}</div>` : '';
      const explanationHtml = q.explanation
        ? `<div class="hq-explanation">${escapeHtml(q.explanation)}</div>` : '';

      return `
        <div class="hq ${resultClass}">
          <div class="hq-header">
            <span class="hq-icon">${resultIcon}</span>
            <span class="badge badge-file">${escapeHtml(q.file_path)}</span>
            <span class="hq-block">${escapeHtml(q.block_name)}</span>
          </div>
          <div class="hq-question">${escapeHtml(q.question_text)}</div>
          <div class="hq-your-answer">Your answer: <strong>${escapeHtml(q.user_answer || '—')}</strong></div>
          ${wrongAnswer}
          ${feedbackHtml}
          ${explanationHtml}
        </div>`;
    }).join('');

    return `
      <div class="history-session">
        <div class="history-session-hdr">
          <span class="hs-date">${date}</span>
          <span class="badge badge-mode">${capitalise(session.mode)}</span>
          <span class="hs-score">${score}</span>
          <span class="hs-cost">${cost}</span>
        </div>
        <div class="history-qs">${qHtml || '<p class="text-muted">No questions recorded.</p>'}</div>
      </div>`;
  }).join('');
}

// ── Session done ─────────────────────────────────────────────────────────────

async function endSession() {
  if (!S.sessionId) return;
  await POST('/api/session/end', { session_id: S.sessionId }).catch(() => {});
}

function showSessionDone(msg) {
  $('done-summary').textContent =
    `${msg} Score this session: ${S.correctCount}/${S.questionCount - 1} correct.`;
  S.sessionId = null;
  S.currentQuestion = null;
  setNavActive('quiz');
  showScreen('done');
}

$('btn-new-session').addEventListener('click', () => {
  S.sessionId = null;
  showScreen('welcome');
  setNavActive('quiz');
  $('btn-start').disabled = false;
});

$('btn-done-stats').addEventListener('click', openStats);

// ── Navigation ───────────────────────────────────────────────────────────────

$('nav-quiz').addEventListener('click', () => {
  setNavActive('quiz');
  if (S.scanComplete && !S.sessionId) {
    showScreen('welcome');
  } else if (S.sessionId && S.currentQuestion) {
    showScreen('quiz');
  } else {
    showScreen('welcome');
  }
});

$('nav-stats').addEventListener('click', openStats);

$('end-session-btn').addEventListener('click', async () => {
  if (!confirm('End session and shut down OwnYourShip?')) return;
  await endSession();
  await POST('/api/shutdown').catch(() => {});
  document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:#8b949e;font-family:sans-serif;font-size:16px;">OwnYourShip has shut down. You can close this tab.</div>';
});

// ── Utilities ────────────────────────────────────────────────────────────────

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function capitalise(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Init ─────────────────────────────────────────────────────────────────────

boot().catch(e => {
  console.error('Boot failed:', e);
  showScreen('welcome');
  $('welcome-subtitle').textContent = 'Failed to connect to server: ' + e.message;
});
