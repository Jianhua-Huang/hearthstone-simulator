/** Browser regression for the local demo. Uses only visible DOM and ordinary UI
 * controls. No Game state, hidden observations, or fixture injection is used. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

const args = Object.fromEntries(process.argv.slice(2).reduce((rows, value, i, all) => {
  if (value.startsWith('--')) rows.push([value.slice(2), all[i + 1]]);
  return rows;
}, []));
const baseUrl = args.url || 'http://127.0.0.1:8765/';
const output = path.resolve(args.output || `outputs/web-ui-battle-polish-20261014/browser-${Date.now()}`);
const playwrightPath = args.playwright || 'C:/Users/Administrator/.codex/skills/develop-web-game/node_modules/playwright/index.mjs';
const { chromium } = await import(pathToFileURL(playwrightPath));
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const report = { started: new Date().toISOString(), url: baseUrl, scenarios: [], checks: [], captures: [], consoleErrors: [], expectedConsoleErrors: [], pageErrors: [], actionRequests: [], busyLockChecks: [], cardHitPoints: [] };
async function sourceHashes() {
  return Object.fromEntries(await Promise.all(['web_ui/static/app.js', 'web_ui/static/style.css', 'web_ui/static/index.html', 'web_ui/server.py', 'tools/test_web_ui_browser.mjs'].map(async file => [file, createHash('sha256').update(await fs.readFile(file)).digest('hex')])));
}
report.sourceBefore = await sourceHashes();
let currentPage;
let scenario = '';
let expectingRejectedView = false;
let capturedAnimation = false;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const check = (name, details = {}) => { report.checks.push({ scenario, name, ...details }); console.log(`PASS ${scenario}: ${name}`); };
const own = m => m.observation.players.find(p => p.id === m.seat);
const enemy = m => m.observation.players.find(p => p.id !== m.seat);
const cardRef = (m, cardId, area = 'hand') => own(m)[area].find(c => c.card_id === cardId)?.ref;
const byRef = (page, ref) => page.locator(`.card[data-ref="${ref}"]`);
async function hoverVisible(page, locator) {
  await page.mouse.move(4, 4);
  await delay(180);
  const point = await locator.evaluate(n => {
    const r = n.getBoundingClientRect();
    for (const yf of [0.5, 0.3, 0.7, 0.15, 0.85]) for (const xf of [0.12, 0.25, 0.4, 0.5, 0.65, 0.8, 0.9]) {
      const x = r.left + r.width * xf, y = r.top + r.height * yf;
      if (x >= 0 && x < innerWidth && y >= 0 && y < innerHeight && document.elementFromPoint(x, y)?.closest('.card') === n) return { x, y };
    }
    return null;
  });
  assert.ok(point, `Card has no reachable visible hit area: ${await locator.getAttribute('aria-label')}`);
  report.cardHitPoints.push({ scenario, ref: await locator.getAttribute('data-ref'), name: await locator.getAttribute('aria-label'), viewport: page.viewportSize(), ...point });
  await page.mouse.move(point.x, point.y);
  await delay(200);
}
async function clickCard(page, ref) {
  const locator = byRef(page, ref);
  await hoverVisible(page, locator);
  await locator.click();
}
async function state(page) { return JSON.parse(await page.locator('#dto').textContent()); }
async function settled(page) {
  await page.waitForFunction(() => !document.querySelector('#refresh')?.disabled && document.body.dataset.busy !== 'true', null, { timeout: 20000 });
  await delay(80);
}
async function responseState(page, response) {
  assert.equal(response.status(), 200, await response.text());
  const value = await response.json();
  if ('accepted' in value) assert.equal(value.accepted, true, JSON.stringify(value.command_error));
  const requestAction = response.request().postDataJSON()?.action;
  if (!capturedAnimation && value.accepted && requestAction?.type === 'play_card' && requestAction.target) {
    await page.waitForFunction(() => document.querySelector('#fx-layer .fx-projectile') && document.getAnimations().some(a => a.playState === 'running'), null, { timeout: 4000, polling: 'raf' });
    const animation = await page.evaluate(() => ({ running: document.getAnimations().filter(a => a.playState === 'running').length, projectiles: document.querySelectorAll('#fx-layer .fx-projectile').length, busy: document.body.dataset.busy, enabledCards: document.querySelectorAll('#players .card:not(:disabled)').length }));
    assert.equal(animation.busy, 'true'); assert.equal(animation.enabledCards, 0);
    const file = path.join(output, 'spell-mid-animation.png');
    await page.screenshot({ path: file, fullPage: true, animations: 'allow' });
    report.captures.push({ name: 'spell-mid-animation', file, animation });
    check('targeted spell produces an actual running projectile animation', animation);
    capturedAnimation = true;
  }
  if (value.revision) await page.waitForFunction(revision => {
    try { return JSON.parse(document.getElementById('dto').textContent).revision === revision; } catch { return false; }
  }, value.revision, { timeout: 20000 });
  const lock = await page.evaluate(() => ({ busy: document.body.dataset.busy, enabledCards: document.querySelectorAll('#players .card:not(:disabled)').length }));
  if (lock.busy === 'true') {
    assert.equal(lock.enabledCards, 0, 'Newly rendered cards must stay disabled until the animation completes.');
    report.busyLockChecks.push({ scenario, action: requestAction?.type || 'test/mana', ...lock });
  }
  await settled(page);
  return value;
}
async function command(page, action, type) {
  const pending = page.waitForResponse(r => r.url().endsWith('/api/action') && (!type || r.request().postDataJSON().action.type === type), { timeout: 20000 });
  pending.catch(() => {});
  await action();
  return responseState(page, await pending);
}
async function mana(page, amount) {
  const pending = page.waitForResponse(r => r.url().endsWith('/api/test/mana'), { timeout: 20000 });
  if (amount === 10) await page.locator('#mana-ten').click();
  else {
    await page.locator('#test-mana').fill(String(amount));
    await page.locator('#apply-mana').click();
  }
  return responseState(page, await pending);
}
async function newScenario(name) {
  scenario = name;
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  currentPage = page;
  page.on('console', message => {
    if (message.type() !== 'error') return;
    const entry = { scenario: name, text: message.text() };
    if (expectingRejectedView && /403/.test(message.text())) report.expectedConsoleErrors.push({ ...entry, reason: 'Deliberately injected expired-session HTTP response' });
    else report.consoleErrors.push(entry);
  });
  page.on('pageerror', error => report.pageErrors.push({ scenario: name, message: error.message }));
  page.on('request', request => {
    if (request.url().endsWith('/api/action')) report.actionRequests.push({ scenario: name, action: request.postDataJSON().action });
  });
  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await page.locator('#preset').selectOption('practice');
  await page.locator('#opponent-mode').selectOption('human');
  await page.locator('#create').click();
  await page.waitForFunction(() => document.querySelector('#dto').textContent.startsWith('{'));
  await settled(page);
  const m = await state(page);
  assert.equal(m.seat, 1);
  report.scenarios.push(name);
  return page;
}
async function capture(page, name) {
  await page.mouse.move(4, 4);
  await delay(450);
  const file = path.join(output, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  const visible = await page.evaluate(() => JSON.parse(window.render_game_to_text()));
  await fs.writeFile(path.join(output, `${name}-visible.json`), JSON.stringify(visible, null, 2));
  report.captures.push({ name, file });
  return file;
}
async function layouts(page, label) {
  for (const viewport of [{ width: 980, height: 872 }, { width: 1280, height: 720 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.mouse.move(4, 4);
    await delay(400);
    const metrics = await page.evaluate(() => {
      const box = n => { const b = n.getBoundingClientRect(); return { x: b.x, y: b.y, width: b.width, height: b.height, right: b.right, bottom: b.bottom }; };
      const images = [...document.querySelectorAll('.card img')].map(img => ({ ref: img.closest('.card').dataset.ref, kind: img.closest('.card').dataset.kind, loaded: img.complete && img.naturalWidth > 0, image: box(img), parent: box(img.closest('.card')) }));
      const cards = [...document.querySelectorAll('.card')].map(c => ({ ref: c.dataset.ref, kind: c.dataset.kind, zone: c.dataset.zone, ...box(c) }));
      const information = [...document.querySelectorAll('.friendly .mana-display, .friendly .player-info > span')].map(n => ({ text: n.textContent, ...box(n) }));
      const hand = [...document.querySelectorAll('.friendly .hand .card')].map(box);
      const coveredInformation = information.flatMap(info => hand.filter(card => Math.min(info.right, card.right) - Math.max(info.x, card.x) > 2 && Math.min(info.bottom, card.bottom) - Math.max(info.y, card.y) > 2).map(card => ({ info, card })));
      const table = document.getElementById('battle-table');
      return { width: innerWidth, height: innerHeight, documentWidth: document.documentElement.scrollWidth, documentHeight: document.documentElement.scrollHeight, table: box(table), tableScroll: { left: table.scrollLeft, top: table.scrollTop, width: table.scrollWidth, height: table.scrollHeight }, images, cards, information, coveredInformation };
    });
    const id = `${label}-${viewport.width}x${viewport.height}`;
    await fs.writeFile(path.join(output, `${id}-layout.json`), JSON.stringify(metrics, null, 2));
    await capture(page, id);
    assert.ok(metrics.documentWidth <= viewport.width + 1, `${id}: horizontal document overflow ${metrics.documentWidth}`);
    for (const image of metrics.images) {
      assert.ok(image.loaded, `${id}: unloaded portrait ${image.ref}`);
      assert.ok(image.image.width <= image.parent.width + 2 && image.image.height <= image.parent.height + 2,
        `${id}: unbounded ${image.kind} portrait ${image.ref} ${JSON.stringify(image)}`);
      assert.ok(image.image.x >= image.parent.x - 2 && image.image.right <= image.parent.right + 2 && image.image.y >= image.parent.y - 2 && image.image.bottom <= image.parent.bottom + 2,
        `${id}: portrait leaves card ${image.ref}`);
    }
    for (const card of metrics.cards) {
      assert.ok(card.x >= -1 && card.right <= viewport.width + 1, `${id}: card outside viewport ${card.ref}`);
      assert.ok(card.width < 250 && card.height < 320, `${id}: oversized ${card.kind} ${card.ref}`);
    }
    assert.ok(metrics.table.bottom <= viewport.height + 2, `${id}: table bottom ${metrics.table.bottom} below viewport`);
    assert.equal(metrics.tableScroll.left, 0, `${id}: tabletop has unintended horizontal scroll offset`);
    assert.equal(metrics.tableScroll.top, 0, `${id}: tabletop has unintended vertical scroll offset`);
    assert.ok(metrics.information.every(info => info.x >= 0 && info.right <= viewport.width && info.y >= 0 && info.bottom <= viewport.height), `${id}: resource information clipped outside viewport`);
    assert.deepEqual(metrics.coveredInformation, [], `${id}: hand overlaps mana or deck information`);
    check(`${id} bounds and image containment`, { document: [metrics.documentWidth, metrics.documentHeight], table: metrics.table, images: metrics.images.length });
    if (label === 'full-hand') {
      for (const edge of ['first', 'last']) {
        const handCards = page.locator('.friendly .hand .card');
        await hoverVisible(page, handCards[edge]());
        await page.locator('#card-preview').waitFor({ state: 'visible' });
        const preview = await page.evaluate(() => {
          const r = document.getElementById('card-preview').getBoundingClientRect();
          const overlaps = [...document.querySelectorAll('.friendly .mana-display, .friendly .player-info > span')].filter(n => {
            const q = n.getBoundingClientRect();
            return Math.min(r.right, q.right) - Math.max(r.left, q.left) > 2 && Math.min(r.bottom, q.bottom) - Math.max(r.top, q.top) > 2;
          }).map(n => n.textContent);
          return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, overlaps };
        });
        assert.ok(preview.x >= 0 && preview.y >= 0 && preview.right <= viewport.width && preview.bottom <= viewport.height, `${id}: ${edge} hand preview clipped`);
        assert.deepEqual(preview.overlaps, [], `${id}: ${edge} hand preview covers resources`);
        check(`${id} ${edge} hand preview readable without covering resources`, preview);
        if (edge === 'last' && viewport.width === 980) {
          const file = path.join(output, 'full-hand-980x872-hover-preview.png');
          await page.screenshot({ path: file, fullPage: true });
          report.captures.push({ name: 'full-hand-980x872-hover-preview', file });
        }
        await page.mouse.move(4, 4);
        await page.locator('#card-preview').waitFor({ state: 'hidden' });
      }
    }
  }
}
async function endAndHandoff(page) {
  await command(page, () => page.locator('#end').click(), 'end_turn');
  await page.locator('#switch').click();
  await page.locator('#curtain').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#players .card').count(), 0);
  assert.equal(await page.locator('#dto').textContent(), '');
  assert.equal(await page.locator('#choice input').count(), 0);
  assert.equal(await page.locator('#actions button').count(), 0);
  const pending = page.waitForResponse(r => r.url().endsWith('/api/ready'));
  await page.locator('#ready').click();
  return responseState(page, await pending);
}
async function playUntargeted(page, ref) {
  return command(page, async () => {
    await clickCard(page, ref);
    await delay(120);
    const confirm = page.locator('#interaction-options button').filter({ hasText: /^确认/ });
    if (await confirm.count() && await confirm.first().isVisible()) await confirm.first().click();
  }, 'play_card');
}
async function playMinion(page, ref, position) {
  return command(page, async () => {
    await clickCard(page, ref);
    await delay(80);
    const m = await state(page);
    const slot = page.locator(`.position-slot[data-owner="${m.seat}"][data-position="${position}"]`);
    if (await slot.isVisible()) {
      if (own(m).board.length >= 6) {
        await page.mouse.move(4, 4);
        const hits = await page.locator('.position-slot:not([hidden])').evaluateAll(nodes => nodes.map(n => {
          const r = n.getBoundingClientRect();
          return { position: n.dataset.position, width: r.width, height: r.height, reachable: document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)?.closest('.position-slot') === n };
        }));
        assert.ok(hits.every(hit => hit.reachable && hit.width > 0 && hit.height > 0), 'Crowded insertion slots must be directly clickable.');
        check('all crowded insertion slots have reachable hit targets', { hits });
      }
      await slot.click();
    }
    else {
      const confirm = page.locator('#interaction-options button').filter({ hasText: /^确认/ });
      if (await confirm.count() && await confirm.first().isVisible()) await confirm.first().click();
    }
    const targets = page.locator('.valid-target');
    if (await targets.count()) {
      const target = await targets.first().getAttribute('data-ref');
      await targets.first().click();
      check('minion battlecry target chosen after position', { source: ref, target, position });
    }
  }, 'play_card');
}

try {
  const page = await newScenario('direct-controls-and-weapon');
  let m = await state(page);
  assert.equal(await page.locator('#diagnostics').getAttribute('open'), null);
  assert.ok(enemy(m).hand.every(card => card.card_id == null));
  check('private enemy hand and collapsed diagnostics');
  m = await mana(page, 0);
  assert.equal(own(m).mana, 0); assert.equal(own(m).max_mana, 0);
  assert.equal(await page.locator('.friendly .hand .card.can-act').count(), 0);
  m = await mana(page, 10);
  assert.equal(own(m).mana, 10); assert.equal(own(m).max_mana, 10);
  check('test mana 0 to 10 changes availability');

  const fireball = cardRef(m, 'CS2_029');
  const beforeCancel = m.revision;
  await byRef(page, fireball).click();
  assert.ok(await page.locator('.valid-target').count() >= 2);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.valid-target').count(), 0);
  assert.equal((await state(page)).revision, beforeCancel);
  await byRef(page, fireball).click();
  m = await command(page, () => byRef(page, enemy(m).hero.ref).click(), 'play_card');
  assert.equal(enemy(m).hero.health, 24); assert.equal(own(m).mana, 6);
  check('targeted spell highlights, Escape cancel, damage and payment');

  const senjin = cardRef(m, 'CS2_179', 'board');
  await byRef(page, senjin).click();
  const beforeInvalid = m.revision;
  await byRef(page, own(m).hero.ref).click();
  await delay(100);
  assert.equal((await state(page)).revision, beforeInvalid);
  assert.ok(await page.locator('.valid-target').count() > 0);
  await page.locator('#cancel-selection').click();
  assert.equal(await page.locator('.valid-target').count(), 0);
  await byRef(page, senjin).click();
  m = await command(page, () => byRef(page, enemy(m).hero.ref).click(), 'attack');
  assert.equal(enemy(m).hero.health, 21);
  check('attack invalid target rejected, button cancel, valid target resolves');

  const yeti = cardRef(m, 'CS2_182');
  await byRef(page, yeti).click();
  assert.equal(await page.locator('.position-slot:not([hidden])').count(), 2);
  await page.locator('#cancel-selection').click();
  m = await playMinion(page, yeti, 1);
  assert.equal(own(m).board[1].card_id, 'CS2_182'); assert.equal(own(m).mana, 2);
  check('minion insertion positions and ordered placement');

  await byRef(page, own(m).hero_power.ref).click();
  assert.ok(await page.locator('.valid-target').count() > 0);
  m = await command(page, () => byRef(page, enemy(m).hero.ref).click(), 'use_hero_power');
  assert.equal(enemy(m).hero.health, 20); assert.equal(own(m).mana, 0);
  check('targeted hero power remains explicit');
  m = await mana(page, 10);
  m = await playUntargeted(page, cardRef(m, 'UNG_029'));
  assert.ok(m.observation.pending_choice?.options?.length >= 1);
  assert.equal(await page.locator('#mana-ten').isDisabled(), true);
  await capture(page, 'discovery-choice');
  await page.locator('#choice input[type=checkbox]').first().check();
  m = await command(page, () => page.getByRole('button', { name: '确认选择', exact: true }).click(), 'select_choice');
  assert.equal(m.observation.pending_choice, null);
  assert.equal(await page.locator('#mana-ten').isEnabled(), true);
  check('real discovery choice and resource guard recovery');

  m = await endAndHandoff(page);
  assert.equal(m.seat, 2); assert.ok(enemy(m).hand.every(card => card.card_id == null));
  check('handoff clears former private DOM and rebinds visible seat');
  await byRef(page, own(m).board[0].ref).click();
  const legalTargets = await page.locator('.valid-target').evaluateAll(nodes => nodes.map(n => n.dataset.ref));
  assert.deepEqual(legalTargets, [enemy(m).board.find(c => c.card_id === 'CS2_179').ref]);
  await page.keyboard.press('Escape');
  check('taunt restricts attack highlight');

  m = await mana(page, 10);
  const power = own(m).hero_power.ref;
  const initialArmor = own(m).hero.armor || 0;
  const oldPowerCount = report.actionRequests.filter(r => r.action.type === 'use_hero_power').length;
  const delayAction = async route => { if (route.request().postDataJSON().action?.type === 'use_hero_power') await delay(300); await route.continue(); };
  await page.route('**/api/action', delayAction);
  m = await command(page, () => byRef(page, power).dblclick({ delay: 20 }), 'use_hero_power');
  await page.unroute('**/api/action', delayAction);
  await delay(400);
  assert.equal(report.actionRequests.filter(r => r.action.type === 'use_hero_power').length - oldPowerCount, 1);
  assert.equal(own(m).mana, 8); assert.equal(own(m).hero.armor, initialArmor + 2);
  assert.equal(await page.locator('#interaction-options button').filter({ hasText: /^确认/ }).count(), 0);
  check('untargeted hero power double click submits once without confirmation');

  const axe = cardRef(m, 'CS2_106');
  assert.ok(axe);
  m = await playUntargeted(page, axe);
  assert.equal(own(m).weapon.card_id, 'CS2_106');
  assert.equal(own(m).hero.attack, own(m).weapon.attack);
  check('weapon equips through visible hand');
  await layouts(page, 'equipped-weapon');

  const selectedPrivate = own(m).hand.find(c => c.kind === 'minion');
  assert.ok(selectedPrivate);
  await byRef(page, selectedPrivate.ref).click();
  const privateName = m.names[selectedPrivate.card_id];
  assert.ok((await page.locator('#interaction-hint').textContent()).includes(privateName));
  expectingRejectedView = true;
  const expireView = route => route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ error: 'seat_session_required' }) });
  await page.route('**/api/view', expireView);
  await page.locator('#refresh').click();
  await page.locator('#welcome').waitFor({ state: 'visible' });
  await delay(150);
  for (const selector of ['#players', '#actions', '#choice', '#interaction-options', '#card-preview']) assert.equal(await page.locator(selector).textContent(), '');
  assert.equal(await page.locator('#dto').textContent(), '');
  assert.equal(await page.locator('#interaction-hint').textContent(), '');
  assert.equal(await page.locator('#cancel-selection').isVisible(), false);
  assert.equal(await page.locator('#card-preview').isVisible(), false);
  await page.unroute('**/api/view', expireView);
  expectingRejectedView = false;
  check('expired-session response clears selected private content', { method: 'Frontend /api/view 403 response injection; no actual server restart' });
  await capture(page, 'expired-session-cleared');

  const singleTarget = await newScenario('single-battlecry-target-stays-explicit');
  m = await state(singleTarget);
  let singleTargetTurns = 0;
  while (!(m.seat === 1 && cardRef(m, 'EX1_019')) && singleTargetTurns < 12) {
    m = await endAndHandoff(singleTarget); singleTargetTurns++;
  }
  assert.equal(m.seat, 1); assert.equal(own(m).board.length, 1);
  const cleric = cardRef(m, 'EX1_019');
  assert.ok(cleric);
  const soleTarget = own(m).board[0];
  const clericActions = m.actions.filter(a => a.type === 'play_card' && a.card === cleric);
  assert.equal(clericActions.length, 2);
  assert.ok(clericActions.every(a => a.target === soleTarget.ref));
  const beforeBattlecry = m.revision;
  const requestsBeforeBattlecry = report.actionRequests.length;
  await byRef(singleTarget, cleric).click();
  assert.equal(await singleTarget.locator('.position-slot:not([hidden])').count(), 2);
  await singleTarget.locator('.position-slot[data-owner="1"][data-position="1"]').click();
  await delay(120);
  assert.equal((await state(singleTarget)).revision, beforeBattlecry);
  assert.equal(report.actionRequests.length, requestsBeforeBattlecry);
  assert.deepEqual(await singleTarget.locator('.valid-target').evaluateAll(nodes => nodes.map(n => n.dataset.ref)), [soleTarget.ref]);
  await capture(singleTarget, 'single-battlecry-awaiting-target');
  m = await command(singleTarget, () => byRef(singleTarget, soleTarget.ref).click(), 'play_card');
  assert.equal(own(m).board.length, 2); assert.equal(own(m).board[1].card_id, 'EX1_019');
  assert.equal(own(m).board[0].attack, soleTarget.attack + 1);
  assert.equal(own(m).board[0].health, soleTarget.health + 1);
  check('single battlecry target requires explicit target click after position', { turn: m.observation.turn, target: soleTarget.ref });

  const crowded = await newScenario('natural-full-hand-and-board');
  m = await state(crowded);
  let turns = 0;
  while (!(m.seat === 1 && own(m).hand.length === 10) && turns < 24) { m = await endAndHandoff(crowded); turns++; }
  assert.equal(m.seat, 1); assert.equal(own(m).hand.length, 10);
  check('10-card hand reached by normal turn draws', { turn: m.observation.turn, hand: own(m).hand.length });
  await layouts(crowded, 'full-hand');
  let refillTurns = 0;
  while (own(m).board.length < 7) {
    const minion = own(m).hand.find(c => c.kind === 'minion' && m.actions.some(a => a.type === 'play_card' && a.card === c.ref));
    if (!minion) {
      m = await mana(crowded, 10);
      const payable = own(m).hand.find(c => c.kind === 'minion' && m.actions.some(a => a.type === 'play_card' && a.card === c.ref));
      if (payable) m = await playMinion(crowded, payable.ref, own(m).board.length);
      else {
        assert.ok(refillTurns < 12, `natural draws exhausted before full board at size ${own(m).board.length}`);
        m = await endAndHandoff(crowded);
        m = await endAndHandoff(crowded);
        refillTurns += 2;
        assert.equal(m.seat, 1);
        assert.equal(m.observation.status, 'playing');
      }
    } else m = await playMinion(crowded, minion.ref, own(m).board.length);
  }
  assert.equal(own(m).board.length, 7);
  check('7-minion battlefield reached by normal hand plays', { additionalDrawTurns: refillTurns });
  await layouts(crowded, 'full-board');
  assert.deepEqual(report.consoleErrors, []); assert.deepEqual(report.pageErrors, []);
  check('no browser console or runtime errors');
  report.sourceAfter = await sourceHashes();
  assert.deepEqual(report.sourceAfter, report.sourceBefore, 'Browser source changed during run; repeat after final changes.');
  check('browser source bytes unchanged during regression');
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.failure = { scenario, message: error.message, stack: error.stack };
  console.error(error);
  if (currentPage && !currentPage.isClosed()) {
    try { await currentPage.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }); } catch {}
    try { await fs.writeFile(path.join(output, 'failure-visible.json'), await currentPage.evaluate(() => window.render_game_to_text())); } catch {}
  }
  process.exitCode = 1;
} finally {
  report.sourceAfter = await sourceHashes();
  report.sourcesStable = JSON.stringify(report.sourceAfter) === JSON.stringify(report.sourceBefore);
  report.finished = new Date().toISOString();
  await fs.writeFile(path.join(output, 'browser-regression.json'), JSON.stringify(report, null, 2));
  await browser.close();
  console.log(`Report: ${output}`);
}
