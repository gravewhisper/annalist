#!/usr/bin/env node
// Drive the served Annalist site with one headless Chromium shell and record proof.
//
// Usage: node drive.mjs [--run DIR] [--name REPORT] [--theme light|dark] [--size 1360x900] STEP...
//
// DIR defaults to runs/verify-annalist/latest. Reads BASE and EVIDENCE from DIR/state.env.
// Each STEP is one argument, fields split on '|':
//   goto|#n=3&p=home        full page load of BASE + hash, wait for the app to render
//   click|SELECTOR          Playwright selector, e.g. role=button[name="Next chapter"]
//   fill|SELECTOR|TEXT      type into an input
//   press|KEY               keyboard press on the focused element (e.g. Enter, ArrowRight)
//   wait|SELECTOR           wait until visible
//   expect|SELECTOR|TEXT    fail unless the element's text contains TEXT
//   absent|SELECTOR|TEXT    fail if the element's text contains TEXT (empty TEXT: fail if the element exists)
//   text|SELECTOR           record the element's text
//   count|SELECTOR          record how many elements match
//   hash                    record location.hash
//   aria|NAME[|SELECTOR]    write EVIDENCE/NAME.aria.yml (default selector #main)
//   shot|NAME[|SELECTOR]    write EVIDENCE/NAME.png (full page, or one element)
// Writes EVIDENCE/REPORT.json (default report name: drive) and prints it.
// Exit 0 when every step passed and the page logged no errors, 1 otherwise.
import {readFileSync, writeFileSync, existsSync, readdirSync, mkdirSync} from 'node:fs';
import {createRequire} from 'node:module';
import {homedir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const args = process.argv.slice(2);
const opt = {run: path.join(ROOT, 'runs/verify-annalist/latest'), name: 'drive', theme: 'light', size: '1360x900'};
while (args[0]?.startsWith('--')) { const k = args.shift().slice(2); opt[k] = args.shift(); }
const state = Object.fromEntries(readFileSync(path.join(opt.run, 'state.env'), 'utf8').trim().split('\n').map(l => l.split(/=(.*)/s).slice(0, 2)));
if (state.CLEANED) { console.error(`${opt.run} was cleaned up at ${state.CLEANED}; run launch.sh for a new instance`); process.exit(2); }
if (!state.BASE) { console.error('state.env has no BASE: was the site served (launch.sh without --no-serve)?'); process.exit(2); }
const EVIDENCE = state.EVIDENCE;
mkdirSync(EVIDENCE, {recursive: true});

async function loadPlaywright() {
  for (const name of ['playwright', 'playwright-core']) {
    try { return await import(name); } catch {}
  }
  const mise = path.join(homedir(), '.local/share/mise/installs/npm-playwright');
  for (const v of existsSync(mise) ? readdirSync(mise).sort().reverse() : []) {
    const base = path.join(mise, v);
    try { return createRequire(path.join(base, 'x.js'))('playwright'); } catch {}
    const core = path.join(base, 'node_modules/.mise');
    for (const d of existsSync(core) ? readdirSync(core).filter(d => d.startsWith('playwright-core@')) : []) {
      const p = path.join(core, d, 'node_modules/playwright-core/index.mjs');
      if (existsSync(p)) return await import(p);
    }
  }
  throw new Error('playwright not found; install it with mise or npm');
}
function headlessShell() {
  const cache = path.join(homedir(), '.cache/ms-playwright');
  const dir = existsSync(cache) ? readdirSync(cache).filter(d => d.startsWith('chromium_headless_shell-')).sort().reverse()[0] : null;
  const exe = dir && path.join(cache, dir, 'chrome-headless-shell-linux64/chrome-headless-shell');
  if (exe && existsSync(exe)) return exe;
  console.error(`chrome-headless-shell not found under ${cache}. Install it with: npx playwright install chromium-headless-shell. This harness never falls back to full Chromium (repo rule).`);
  process.exit(2);
}

const {chromium} = await loadPlaywright();
const [w, h] = opt.size.split('x').map(Number);
const browser = await chromium.launch({headless: true, executablePath: headlessShell()});
const report = {base: state.BASE, build: state.BUILD_SHA, theme: opt.theme, steps: [], errors: [], ok: true};
try {
  const ctx = await browser.newContext({viewport: {width: w, height: h}, colorScheme: opt.theme});
  await ctx.addInitScript(t => { try { localStorage.setItem('wiki-theme', t); } catch {} }, opt.theme);
  const page = await ctx.newPage();
  page.on('pageerror', e => report.errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') report.errors.push(m.text()); });
  const rendered = () => page.waitForFunction(() => document.getElementById('nlab')?.textContent !== '', null, {timeout: 10000});
  for (const raw of args) {
    const [verb, a = '', b = ''] = raw.split('|');
    const step = {step: raw, ok: true};
    try {
      if (verb === 'goto') {
        await page.goto('about:blank');
        await page.goto(state.BASE + 'index.html' + (a.startsWith('#') ? a : '#' + a), {waitUntil: 'networkidle'});
        await rendered();
        step.hash = await page.evaluate(() => location.hash);
      } else if (verb === 'click') { await page.locator(a).first().click(); await page.waitForTimeout(150); step.hash = await page.evaluate(() => location.hash); }
      else if (verb === 'fill') { await page.locator(a).first().fill(b); await page.waitForTimeout(100); }
      else if (verb === 'press') { await page.keyboard.press(a); await page.waitForTimeout(150); step.hash = await page.evaluate(() => location.hash); }
      else if (verb === 'wait') await page.locator(a).first().waitFor({state: 'visible', timeout: 5000});
      else if (verb === 'expect' || verb === 'absent') {
        const loc = page.locator(a);
        const n = await loc.count();
        const text = n ? (await loc.allInnerTexts()).join('\n') : '';
        const has = verb === 'absent' && !b ? n > 0 : text.includes(b);
        step.ok = verb === 'expect' ? n > 0 && has : !has;
        step.found = n;
        if (!step.ok) step.text = text.slice(0, 600);
      } else if (verb === 'text') step.text = (await page.locator(a).allInnerTexts()).join('\n').slice(0, 2000);
      else if (verb === 'count') step.count = await page.locator(a).count();
      else if (verb === 'hash') step.hash = await page.evaluate(() => location.hash);
      else if (verb === 'aria') {
        const file = path.join(EVIDENCE, `${a}.aria.yml`);
        writeFileSync(file, await page.locator(b || '#main').first().ariaSnapshot());
        step.file = file;
      } else if (verb === 'shot') {
        const file = path.join(EVIDENCE, `${a}.png`);
        await (b ? page.locator(b).first().screenshot({path: file}) : page.screenshot({path: file, fullPage: true}));
        step.file = file;
      } else throw new Error(`unknown verb ${verb}`);
    } catch (e) { step.ok = false; step.error = String(e).split('\n')[0]; }
    report.steps.push(step);
    if (!step.ok) report.ok = false;
  }
} finally {
  await browser.close();
}
if (report.errors.length) report.ok = false;
const out = path.join(EVIDENCE, `${opt.name}.json`);
writeFileSync(out, JSON.stringify(report, null, 1));
console.log(JSON.stringify(report, null, 1));
process.exit(report.ok ? 0 : 1);
