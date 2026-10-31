/** AI-opponent browser regression: seat-projected DOM and ordinary API only. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { chromium } from 'file:///C:/Users/Administrator/.codex/skills/develop-web-game/node_modules/playwright/index.mjs';

const cli = Object.fromEntries(process.argv.slice(2).reduce((rows, value, i, all) => {
  if (value.startsWith('--')) rows.push([value.slice(2), all[i + 1]]); return rows;
}, []));
const base = cli.url || 'http://127.0.0.1:8765/';
const output = path.resolve(cli.output || `outputs/web-ui-opponent-20261014/browser-${Date.now()}`);
await fs.mkdir(output, { recursive: true });
const hash = value => createHash('sha256').update(value).digest('hex');
const files = ['web_ui/server.py', 'web_ui/bot.py', 'web_ui/static/app.js', 'web_ui/static/style.css', 'web_ui/static/index.html', 'tools/test_web_ui_bot_browser.mjs'];
async function sourceHashes() { return Object.fromEntries(await Promise.all(files.map(async file => [file, hash(await fs.readFile(file))]))); }
const report = { started: new Date().toISOString(), checks: [], stepRequests: [], stepResponses: [], apiChecks: [], captures: [], errors: [], pageErrors: [], privacyViolations: [], sourceBefore: await sourceHashes() };
const browser = await chromium.launch({ headless: true });
const pages = [], observers = [], stepInflight = new Map(), maxInflight = new Map(), boundSeats = new Map();
let currentPage, scenario = '';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const own = m => m.observation.players.find(p => p.id === m.seat);
const foe = m => m.observation.players.find(p => p.id !== m.seat);
const check = (name, details = {}) => { report.checks.push({ scenario, name, ...details }); console.log(`PASS ${scenario}: ${name}`); };
const state = async page => JSON.parse(await page.locator('#dto').textContent());
function auditView(data, expectedSeat, step = false) {
  if (!data.observation) return;
  assert.equal(data.seat, expectedSeat);
  assert.equal(data.opponent.seat, 3 - data.seat);
  for (const key of ['snapshot', 'history', 'rng_state', 'test_segments', 'bot_action', 'opponent_action']) assert.ok(!(key in data), `private response key ${key}`);
  const enemy = foe(data);
  assert.ok(!('deck' in enemy));
  for (const card of enemy.hand) if (card.card_id == null) for (const key of ['cost', 'attack', 'health', 'text']) assert.ok(!(key in card), `unknown hand has ${key}`);
  const choice = data.observation.pending_choice;
  if (choice && choice.player_id !== data.seat) assert.deepEqual(Object.keys(choice), ['player_id']);
  if (step) assert.equal(typeof data.opponent_acted, 'boolean');
}
async function settled(page) { await page.waitForFunction(() => document.body.dataset.busy !== 'true', null, { timeout: 20000 }); }
async function capture(page, name) {
  await page.mouse.move(4, 4); await pause(180);
  const file = path.join(output, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  await fs.writeFile(path.join(output, `${name}-visible.json`), await page.evaluate(() => window.render_game_to_text()));
  report.captures.push({ name, file });
}
async function newGame(name, preset) {
  scenario = name;
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage(); currentPage = page; pages.push(page);
  boundSeats.set(page, 1); stepInflight.set(page, new Set()); maxInflight.set(page, 0);
  page.on('console', message => { if (message.type() === 'error') report.errors.push({ scenario: name, message: message.text() }); });
  page.on('pageerror', error => report.pageErrors.push({ scenario: name, message: error.message }));
  page.on('request', request => {
    if (!request.url().endsWith('/api/opponent/step')) return;
    const body = request.postDataJSON(); const inflight = stepInflight.get(page); inflight.add(request);
    maxInflight.set(page, Math.max(maxInflight.get(page), inflight.size));
    report.stepRequests.push({ scenario: name, at: Date.now(), revision: body.revision, ticketHash: hash(body.ticket), keys: Object.keys(body).sort(), expectedSeat: boundSeats.get(page) });
  });
  const finished = request => stepInflight.get(page).delete(request);
  page.on('requestfinished', finished); page.on('requestfailed', finished);
  page.on('response', response => {
    if (!response.url().includes('/api/')) return;
    const pending = (async () => {
      const body = await response.json();
      if (body.observation) {
        try { auditView(body, body.seat); } catch (error) { report.privacyViolations.push({ scenario: name, error: error.message }); }
      }
      if (response.url().endsWith('/api/opponent/step')) {
        try { auditView(body, boundSeats.get(page), true); } catch (error) { report.privacyViolations.push({ scenario: name, error: error.message }); }
        report.stepResponses.push({ scenario: name, status: response.status(), acted: body.opponent_acted, seat: body.seat, revision: body.revision, turn: body.observation?.turn, active: body.observation?.active_player, pendingActor: body.observation?.pending_choice?.player_id ?? null, error: body.opponent?.error || body.error || null, canStep: body.opponent?.can_step });
      }
    })().catch(error => report.privacyViolations.push({ scenario: name, error: `response read: ${error.message}` }));
    observers.push(pending);
  });
  await page.goto(base, { waitUntil: 'networkidle' });
  assert.equal(await page.locator('#opponent-mode').inputValue(), 'ai');
  await page.locator('#preset').selectOption(preset);
  await page.locator('#create').click();
  await page.waitForFunction(() => document.getElementById('dto').textContent.startsWith('{'));
  await settled(page);
  return page;
}
async function command(page, action, type) {
  const response = page.waitForResponse(r => r.url().endsWith('/api/action') && r.request().postDataJSON().action.type === type, { timeout: 20000 });
  response.catch(() => {}); await action(); const r = await response;
  assert.equal(r.status(), 200); const data = await r.json(); assert.equal(data.accepted, true, data.command_error);
  return data;
}
async function humanTurn(page, minimumTurn, seat = 1) {
  await page.waitForFunction(({ minimumTurn, seat }) => {
    try { const m = JSON.parse(document.getElementById('dto').textContent); return m.seat === seat && m.observation.status === 'playing' && m.observation.turn >= minimumTurn && m.observation.active_player === seat && !m.observation.pending_choice && document.body.dataset.busy !== 'true'; } catch { return false; }
  }, { minimumTurn, seat }, { timeout: 45000 });
  return state(page);
}
async function idleNoSteps(page, label, milliseconds = 1250) {
  await settled(page); await pause(100);
  const before = report.stepRequests.length, revision = (await state(page)).revision;
  await pause(milliseconds);
  assert.equal(report.stepRequests.length, before, `${label}: unwanted AI polling`);
  assert.equal((await state(page)).revision, revision, `${label}: unexpected state change`);
  check(label, { idleMilliseconds: milliseconds });
}
async function api(page, endpoint, body = {}) {
  const token = await page.evaluate(() => sessionStorage.getItem('hs-seat'));
  const response = await page.request.post(base + 'api/' + endpoint, { data: body, headers: { Authorization: 'Bearer ' + token } });
  return { status: response.status(), data: await response.json() };
}
async function mode(page, value) {
  const response = page.waitForResponse(r => r.url().endsWith('/api/opponent'));
  await page.locator('#opponent-mode').selectOption(value);
  const r = await response; assert.equal(r.status(), 200);
  const m = await r.json(); assert.equal(m.opponent.mode, value); await settled(page); return m;
}
async function pauseBot(page) {
  const response = page.waitForResponse(r => r.url().endsWith('/api/opponent'));
  await page.locator('#bot-control').click();
  const r = await response; assert.equal(r.status(), 200); const m = await r.json();
  assert.equal(m.opponent.mode, 'human'); await settled(page); return m;
}

try {
  const constructed = await newGame('constructed-mulligan-and-rounds', 'constructed');
  let m = await state(constructed);
  assert.equal(m.seat, 1); assert.equal(m.opponent.mode, 'ai');
  assert.equal(m.observation.pending_choice.player_id, 1);
  assert.ok(m.observation.pending_choice.options.length > 0);
  assert.equal(await constructed.locator('#switch').isVisible(), false);
  await idleNoSteps(constructed, 'AI does not replace the human mulligan');
  await capture(constructed, 'human-mulligan-awaiting-user');
  const opening = await command(constructed, () => constructed.getByRole('button', { name: '确认选择', exact: true }).click(), 'select_choice');
  assert.deepEqual(opening.observation.pending_choice, { player_id: 2 });
  m = await humanTurn(constructed, 1);
  assert.equal(m.observation.opening_stage, 'complete');
  assert.equal(m.seat, 1); assert.equal(await constructed.locator('#curtain').isVisible(), false);
  assert.equal(await constructed.locator('#choice').isVisible(), false);
  check('opponent mulligan completes automatically without a handoff or blocking modal');
  await idleNoSteps(constructed, 'AI is quiet on the human turn');
  for (let round = 0; round < 4; round++) {
    const turn = m.observation.turn;
    await command(constructed, () => constructed.locator('#end').click(), 'end_turn');
    m = await humanTurn(constructed, turn + 2);
    assert.equal(m.seat, 1); assert.equal(m.opponent.mode, 'ai'); assert.ok(!m.opponent.error);
    check('automatic opponent round returns control', { round: round + 1, turn: m.observation.turn });
  }
  await idleNoSteps(constructed, 'multiple rounds leave no repeating scheduler');
  await capture(constructed, 'constructed-after-four-ai-rounds');
  await constructed.setViewportSize({ width: 980, height: 872 });
  await pause(250);
  const compact = await constructed.evaluate(() => {
    const rect = document.getElementById('opponent-mode').getBoundingClientRect();
    return { documentWidth: document.documentElement.scrollWidth, tableBottom: document.getElementById('battle-table').getBoundingClientRect().bottom, control: { x: rect.x, right: rect.right, top: rect.top, bottom: rect.bottom } };
  });
  assert.ok(compact.documentWidth <= 980 && compact.tableBottom <= 873);
  assert.ok(compact.control.x >= 0 && compact.control.right <= 980 && compact.control.top >= 0 && compact.control.bottom <= 872);
  check('opponent controls remain visible at the compact desktop viewport', compact);
  await capture(constructed, 'constructed-ai-980x872');

  const practice = await newGame('choice-pause-tickets-manual-and-gameover', 'practice');
  m = await state(practice);
  const visions = own(m).hand.find(c => c.card_id === 'UNG_029');
  assert.ok(visions);
  await command(practice, () => practice.locator(`.card[data-ref="${visions.ref}"]`).click(), 'play_card');
  await settled(practice); m = await state(practice);
  assert.equal(m.observation.pending_choice.player_id, m.seat);
  await idleNoSteps(practice, 'AI does not replace the human discovery');
  assert.equal(await practice.locator('#choice').isVisible(), true);
  await practice.locator('#choice input[type=checkbox]').first().check();
  await command(practice, () => practice.getByRole('button', { name: '确认选择', exact: true }).click(), 'select_choice');
  await settled(practice); m = await state(practice);
  assert.equal(m.observation.pending_choice, null);
  check('human discovery resumes only after the explicit user selection');

  const beforePause = m;
  m = await pauseBot(practice);
  assert.equal(await practice.locator('#switch').isVisible(), true);
  await command(practice, () => practice.locator('#end').click(), 'end_turn');
  await settled(practice); m = await state(practice);
  assert.equal(m.observation.active_player, 2);
  await idleNoSteps(practice, 'pause switches the server to manual and stops AI requests');
  const paused = m;
  const staleRevision = await api(practice, 'opponent', { revision: beforePause.revision, ticket: paused.opponent.ticket, mode: 'ai' });
  assert.equal(staleRevision.status, 409); assert.equal(staleRevision.data.error, 'stale_observation');
  const staleTicket = await api(practice, 'opponent', { revision: paused.revision, ticket: beforePause.opponent.ticket, mode: 'ai' });
  assert.equal(staleTicket.status, 409); assert.equal(staleTicket.data.error, 'stale_opponent_step');
  const afterInvalid = (await api(practice, 'view')).data;
  assert.equal(afterInvalid.revision, paused.revision); assert.equal(afterInvalid.opponent.ticket, paused.opponent.ticket);
  assert.equal(afterInvalid.opponent.mode, 'human');
  report.apiChecks.push({ kind: 'stale configuration', revisionError: staleRevision.data.error, ticketError: staleTicket.data.error, unchanged: true });
  check('stale configuration revision and ticket are rejected without advancing');
  await mode(practice, 'ai');
  m = await humanTurn(practice, 3);
  check('selecting AI resumes the paused opposing turn');

  m = await pauseBot(practice);
  await command(practice, () => practice.locator('#end').click(), 'end_turn');
  await settled(practice); m = await state(practice);
  const enabled = await api(practice, 'opponent', { revision: m.revision, ticket: m.opponent.ticket, mode: 'ai' });
  assert.equal(enabled.status, 200);
  const singleRequest = { revision: enabled.data.revision, ticket: enabled.data.opponent.ticket };
  const stepped = await api(practice, 'opponent/step', singleRequest);
  assert.equal(stepped.status, 200); assert.equal(stepped.data.opponent_acted, true); auditView(stepped.data, 1, true);
  const duplicate = await api(practice, 'opponent/step', singleRequest);
  assert.equal(duplicate.status, 409); assert.ok(['stale_observation', 'stale_opponent_step'].includes(duplicate.data.error));
  const afterDuplicate = (await api(practice, 'view')).data;
  assert.equal(afterDuplicate.revision, stepped.data.revision); assert.equal(afterDuplicate.opponent.ticket, stepped.data.opponent.ticket);
  report.apiChecks.push({ kind: 'one-use AI step', firstActed: true, duplicateError: duplicate.data.error, unchanged: true });
  check('current AI step ticket works once and replayed request cannot advance');
  await practice.locator('#refresh').click();
  m = await humanTurn(practice, 5);
  check('refresh continues from the latest AI ticket after a controlled API step');

  await mode(practice, 'human');
  await practice.locator('#switch').click(); await practice.locator('#curtain').waitFor({ state: 'visible' });
  assert.equal(await practice.locator('#players .card').count(), 0);
  assert.equal(await practice.locator('#dto').textContent(), '');
  boundSeats.set(practice, 2);
  await practice.locator('#ready').click(); await settled(practice);
  m = await state(practice); assert.equal(m.seat, 2); assert.equal(m.opponent.mode, 'human');
  await mode(practice, 'ai');
  m = await humanTurn(practice, 6, 2);
  assert.equal(m.opponent.seat, 1); assert.equal(await practice.locator('#switch').isVisible(), false);
  check('manual handoff and re-enabling AI bind the opposite of the new human seat');
  await capture(practice, 'ai-opponent-with-human-seat-two');

  await practice.locator('#diagnostics > summary').click();
  await practice.getByText('完整合法操作', { exact: false }).first().click();
  const concede = practice.locator('#actions button').filter({ hasText: /^认输$/ });
  await concede.click();
  await command(practice, () => concede.click(), 'concede');
  await settled(practice); m = await state(practice);
  assert.notEqual(m.observation.status, 'playing'); assert.equal(m.opponent.can_step, false);
  await idleNoSteps(practice, 'game over stops AI scheduling permanently', 1600);
  await capture(practice, 'gameover-no-ai-loop');

  const inFlight = await newGame('pause-during-inflight-step', 'practice');
  let releaseStep, signalStep;
  const gate = new Promise(resolve => { releaseStep = resolve; });
  const arrived = new Promise(resolve => { signalStep = resolve; });
  let heldRequests = 0;
  const holdStep = async route => { heldRequests++; signalStep(); await gate; await route.continue(); };
  await inFlight.route('**/api/opponent/step', holdStep);
  await command(inFlight, () => inFlight.locator('#end').click(), 'end_turn');
  await Promise.race([arrived, pause(15000).then(() => { throw new Error('AI step was never scheduled for pause test.'); })]);
  assert.equal(await inFlight.locator('#bot-control').isEnabled(), true);
  const configurePause = inFlight.waitForResponse(r => r.url().endsWith('/api/opponent'));
  await inFlight.locator('#bot-control').click();
  await pause(120);
  assert.equal(heldRequests, 1);
  releaseStep();
  const pauseResponse = await configurePause;
  assert.equal(pauseResponse.status(), 200);
  const pausedInFlight = await pauseResponse.json(); assert.equal(pausedInFlight.opponent.mode, 'human');
  await settled(inFlight); await inFlight.unroute('**/api/opponent/step', holdStep);
  await idleNoSteps(inFlight, 'pause remains effective when clicked during a pending AI request');
  check('in-flight pause waits for the current step then disables the server opponent', { heldRequests });
  await mode(inFlight, 'ai');
  await humanTurn(inFlight, 3);
  check('AI can resume after an in-flight pause');
  await capture(inFlight, 'resumed-after-inflight-pause');

  const pendingBot = await newGame('opponent-discovery-after-manual-handoff', 'practice');
  await pauseBot(pendingBot);
  m = await state(pendingBot);
  const pendingVisions = own(m).hand.find(c => c.card_id === 'UNG_029');
  assert.ok(pendingVisions);
  await command(pendingBot, () => pendingBot.locator(`.card[data-ref="${pendingVisions.ref}"]`).click(), 'play_card');
  await settled(pendingBot); m = await state(pendingBot);
  assert.equal(m.observation.pending_choice.player_id, 1);
  assert.equal(await pendingBot.locator('#choice').isVisible(), true);
  await pendingBot.locator('#switch').click(); await pendingBot.locator('#curtain').waitFor({ state: 'visible' });
  boundSeats.set(pendingBot, 2);
  await pendingBot.locator('#ready').click(); await settled(pendingBot);
  m = await state(pendingBot);
  assert.equal(m.seat, 2); assert.deepEqual(m.observation.pending_choice, { player_id: 1 });
  assert.equal(await pendingBot.locator('#choice input').count(), 0);
  const pendingEnabled = await mode(pendingBot, 'ai');
  assert.deepEqual(pendingEnabled.observation.pending_choice, { player_id: 1 });
  assert.equal(pendingEnabled.opponent.can_step, true);
  assert.equal(await pendingBot.locator('#choice').isVisible(), false);
  assert.match(await pendingBot.locator('#interaction-hint').textContent(), /电脑正在完成选择/);
  await capture(pendingBot, 'opponent-discovery-awaiting-ai');
  m = await humanTurn(pendingBot, 2, 2);
  assert.equal(m.observation.pending_choice, null); assert.equal(m.opponent.can_step, false);
  check('AI resolves an existing private discovery and returns the next turn without a modal deadlock');
  await idleNoSteps(pendingBot, 'resolved opponent discovery leaves the human turn idle');
  await capture(pendingBot, 'opponent-discovery-resolved');

  await Promise.all(observers);
  for (const [page, maximum] of maxInflight) assert.ok(maximum <= 1, `overlapping AI requests: ${maximum}`);
  const tickets = report.stepRequests.map(r => r.ticketHash);
  assert.equal(new Set(tickets).size, tickets.length, 'Frontend reused an AI ticket.');
  assert.ok(report.stepRequests.length > 4);
  assert.ok(report.stepRequests.every(r => JSON.stringify(r.keys) === JSON.stringify(['revision', 'ticket'])));
  assert.ok(report.stepResponses.every(r => r.status === 200 && r.acted && !r.error));
  assert.deepEqual(report.privacyViolations, []); assert.deepEqual(report.errors, []); assert.deepEqual(report.pageErrors, []);
  check('AI requests are serial, one-ticket, seat-bound, and reveal no bot action or hidden choice', { steps: report.stepRequests.length, maxInflight: Math.max(...maxInflight.values()) });
  report.sourceAfter = await sourceHashes(); assert.deepEqual(report.sourceAfter, report.sourceBefore);
  check('source bytes remain unchanged throughout the browser regression');
  report.passed = true;
} catch (error) {
  report.passed = false; report.failure = { scenario, message: error.message, stack: error.stack }; console.error(error); process.exitCode = 1;
  if (currentPage && !currentPage.isClosed()) {
    try { await currentPage.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }); } catch {}
    try { await fs.writeFile(path.join(output, 'failure-visible.json'), await currentPage.evaluate(() => window.render_game_to_text())); } catch {}
  }
} finally {
  await Promise.allSettled(observers);
  report.sourceAfter = await sourceHashes(); report.sourcesStable = JSON.stringify(report.sourceAfter) === JSON.stringify(report.sourceBefore);
  report.finished = new Date().toISOString(); report.maxInflight = [...maxInflight.values()];
  await fs.writeFile(path.join(output, 'browser-regression.json'), JSON.stringify(report, null, 2));
  await browser.close(); console.log(`Report: ${output}`);
}
