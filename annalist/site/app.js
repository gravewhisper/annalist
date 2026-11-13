const D = {};
const WIKI = document.currentScript?.dataset.wiki || 'data/wiki.json';
const S = {n: 1, p: 'home', tab: '', m: '', sort: ''};
const HASH_KEYS = ['n', 'p', 'tab', 'm', 'sort'];
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const cap = s => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
const label = key => cap(key.replace(/_/g, ' '));
const catName = t => { const l = D.book.labels?.[t]; return l && l.chapter <= S.n ? l.text : cap(plural(t)); };
const plural = t => t === 'uncategorized' ? t : /[^aeiou]y$/.test(t) ? t.slice(0, -1) + 'ies' : /(s|x|ch|sh)$/.test(t) ? t + 'es' : t + 's';
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
};
const until = (rows, key = 'chapter') => rows.filter(r => (r.shown ?? r[key]) <= S.n);
const latest = (rows, key = 'chapter') => until(rows, key).at(-1);
let more = 60;

async function load() {
  const data = await fetch(WIKI).then(r => r.json());
  Object.assign(D, data);
  D.byId = Object.fromEntries(D.entities.map(e => [e.id, e]));
  D.ch = Object.fromEntries(D.chapters.map(c => [c.n, c]));
  D.factsBy = {};
  for (const f of D.facts) (D.factsBy[f.entity] ||= []).push(f);
  D.relsBy = {};
  for (const r of D.relations) for (const id of new Set([r.source, r.target])) (D.relsBy[id] ||= []).push(r);
  D.parts = {};
  for (const e of D.entities) if (e.merged) (D.parts[e.merged.into] ||= []).push(e.id);
  D.namesakes = {};
  for (const e of D.entities) (D.namesakes[e.name] ||= []).push(e.id);
  D.power = new Set(D.book.power_types);
  D.parents = D.book.parents || {};
  D.tl = Object.fromEntries((D.timelines || []).map(t => [t.id, t]));
  D.storeKey = 'wiki-chapter:' + D.book.title;
  const typeCount = {};
  for (const e of D.entities) typeCount[e.type] = (typeCount[e.type] || 0) + 1;
  for (const e of D.entities) if (e.retyped) { const now = e.type; Object.defineProperty(e, 'type', {get: () => S.n >= e.retyped.chapter ? now : e.retyped.from}); }
  D.typeOrder = Object.keys(typeCount).sort((a, b) => typeCount[b] - typeCount[a] || a.localeCompare(b));
  applyTheme(D.book.theme || {});
  document.title = D.book.title;
  $('brand').textContent = D.book.title;
  $('n').max = D.book.max;
}

function applyTheme(theme) {
  const vars = obj => Object.entries(obj || {}).map(([k, v]) => `--${k.replace(/^--/, '')}:${v}`).join(';');
  let css = `:root[data-theme="light"]{${vars(theme.light)}}:root[data-theme="dark"]{${vars(theme.dark)}}`;
  if (theme.heading_font) css += `:root{--heading-font:"${theme.heading_font}",Georgia,serif}`;
  if (theme.body_font) css += `:root{--body-font:"${theme.body_font}",system-ui,sans-serif}`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
  for (const href of [].concat(theme.font_url || [])) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }
}

function setTheme(t) {
  document.documentElement.dataset.theme = t;
  store.set('wiki-theme', t);
}

const live = id => {
  const e = D.byId[id];
  return e?.merged && e.merged.chapter <= S.n ? e.merged.into : id;
};
const vis = e => !!e && e.first <= S.n && live(e.id) === e.id;
const pageIds = id => [id, ...(D.parts[id] || []).filter(p => live(p) === id)];
const visAliases = e => until(e.aliases).map(a => a.name);
const nameAt = (e, c) => e.name_chapter <= c ? e.name : e.aliases.find(a => (a.shown ?? a.chapter) <= c)?.name;
function displayName(e, among) {
  if (e.name_chapter > S.n) return nameAt(e, S.n) || e.name;
  if (among === e.type) return e.name;
  const others = D.namesakes[e.name].map(id => D.byId[id]).filter(o => o.id !== e.id && vis(o));
  if (!others.length) return e.name;
  if (others.some(o => o.type !== e.type) && !searchKey(e.name).endsWith(searchKey(e.type))) return `${e.name} (${e.type})`;
  return `${e.name} (ch ${e.first})`;
}
const visNames = e => [...new Set([e.name_chapter <= S.n ? e.name : null, ...visAliases(e)].filter(Boolean))];
const searchKey = s => s.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().replace(/['’ʼ`]/g, '').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
const inOrder = (q, t) => { let i = 0; for (const ch of t) if (ch === q[i]) i++; return i === q.length; };
function typosToPrefix(q, t) {
  let before = [], prev = Array.from({length: t.length + 1}, (_, j) => j);
  for (let i = 1; i <= q.length; i++) {
    const row = [i];
    for (let j = 1; j <= t.length; j++) {
      row[j] = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (q[i - 1] !== t[j - 1]));
      if (i > 1 && j > 1 && q[i - 1] === t[j - 2] && q[i - 2] === t[j - 1]) row[j] = Math.min(row[j], before[j - 2] + 1);
    }
    [before, prev] = [prev, row];
  }
  return Math.min(...prev);
}
function nameRank(q, name) {
  const n = searchKey(name), flat = q.replace(/ /g, ''), nflat = n.replace(/ /g, '');
  const starts = [0, ...[...n.matchAll(/ /g)].map(m => m.index + 1)], words = n.split(' '), asked = q.split(' ');
  if (n === q || nflat === flat) return 0;
  if (n.startsWith(q)) return 1;
  if (starts.some(i => n.startsWith(q, i))) return 2;
  if (asked.length > 1 && asked.every(w => words.some(x => x.startsWith(w)))) return 3;
  if (nflat.includes(flat)) return 4;
  if (inOrder(flat, nflat)) return 5;
  const slack = flat.length >= 8 ? 2 : flat.length >= 4 ? 1 : 0;
  return slack && starts.some(i => typosToPrefix(q, n.slice(i)) <= slack) ? 6 : -1;
}
function findEntries(query, entities, tie = () => 0) {
  const q = searchKey(query);
  if (!q) return [];
  const hits = [];
  for (const e of entities) {
    let best = null;
    for (const via of visNames(e)) {
      const rank = nameRank(q, via);
      if (rank >= 0 && (!best || rank < best.rank)) best = {e, via, rank};
    }
    if (best) hits.push(best);
  }
  return hits.sort((a, b) => a.rank - b.rank || tie(a.e, b.e));
}
const hitName = ({e, via}) => esc(displayName(e)) + (via !== displayName(e) && via !== e.name ? ` <small>(${esc(via)})</small>` : '');
const visFacts = id => until(pageIds(id).flatMap(p => D.factsBy[p] || [])).sort((a, b) => a.chapter - b.chapter);
const visFactsAll = () => D.facts.reduce((a, f) => a + (f.chapter <= S.n), 0);
const visRels = id => until([...new Set(pageIds(id).flatMap(p => D.relsBy[p] || []))]).map(r => ({...r, source: live(r.source), target: live(r.target)}))
  .filter(r => vis(D.byId[r.source]) && vis(D.byId[r.target])).sort((a, b) => a.chapter - b.chapter);
let fullCache = {n: -1};
const full = e => {
  if (fullCache.n !== S.n) fullCache = {n: S.n, ids: new Set(D.entities.filter(x => vis(x) && (visFacts(x.id).length || visRels(x.id).length)).map(x => x.id))};
  return fullCache.ids.has(e?.id);
};
const minor = e => vis(e) && !full(e);

function role(tid) {
  const t = D.tl[tid];
  if (!t || t.kind === 'main') return 'current';
  if (t.erased != null && t.erased <= S.n) return 'erased';
  return t.kind === 'run' ? 'current' : 'aside';
}
const tlName = t => esc(t.label || t.id) + (t.period && !(t.label || '').includes(t.period) ? `, ${esc(t.period)}` : '');
function tlBadge(tid) {
  const r = role(tid);
  if (r === 'current') return '';
  const t = D.tl[tid];
  return r === 'erased' ? `<span class="badge erased">erased timeline</span>` : `<span class="badge aside">${esc(t.kind)}: ${tlName(t)}</span>`;
}

function lede(e) {
  if (e.summary && e.summary.chapter <= S.n) return {text: e.summary.text, chapter: null};
  const s = latest(e.summaries || []);
  if (s) return s;
  const b = latest(e.blurbs.filter(([, , tid]) => role(tid) !== 'erased').map(([chapter, text]) => ({chapter, text})));
  if (b) return b;
  const f = visFacts(e.id).at(-1);
  return f ? {text: f.claim, chapter: f.chapter} : {text: '', chapter: null};
}

const TIERS = {series: 'Series mysteries', arc: 'Arc mysteries', cliffhanger: 'Cliffhangers'};
const tierOf = q => q.tier?.series != null && q.tier.series <= S.n ? 'series' : q.tier?.arc != null && q.tier.arc <= S.n ? 'arc' : 'cliffhanger';

const ENDINGS = {'left-open': 'Left open by the ending', unclear: 'Not answered by the end', 'dropped-thread': 'Never followed up'};
const endOf = q => q.ending && q.ending.chapter <= S.n ? q.ending.verdict : null;
const solved = q => q.resolved && until([q.resolved]).length > 0;
const atEnd = q => (q.resolved?.at_end && solved(q)) || endOf(q) === 'answered-implicitly';
const refuted = q => q.premise && q.premise.chapter <= S.n;
const settled = st => st === 'resolved' || st === 'premise-false';

function qState(q) {
  if (q.chapter > S.n) return null;
  if (refuted(q)) return 'premise-false';
  if (solved(q)) return 'resolved';
  if (endOf(q) === 'answered-implicitly') return 'resolved';
  if (endOf(q) === 'dropped-thread') return 'dropped';
  return until(q.leads).length ? 'partial' : 'open';
}

const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
let linkCache = {n: -1};
function linker() {
  if (linkCache.n === S.n) return linkCache;
  const map = {};
  const stepOverGroup = (e, id) => e.type === D.book.ladder?.step_type && D.byId[id].type === D.book.ladder.group_type;
  for (const e of D.entities) if (full(e)) for (const name of visNames(e)) if (name.length > 2 && (!map[name] || stepOverGroup(e, map[name]))) map[name] = e.id;
  const plain = {};
  for (const e of D.entities) for (const name of e.common_names || []) if (map[name] === e.id) plain[name] = new Set(e.linked_chapters);
  const keys = Object.keys(map).sort((a, b) => b.length - a.length).map(reEsc);
  linkCache = {n: S.n, map, plain, re: keys.length ? new RegExp('(?<![\\p{L}\\p{N}])(' + keys.join('|') + ')(?![\\p{L}\\p{N}])', 'gu') : null};
  return linkCache;
}
function unnamedAt(e) { return !!e.nameless && !(e.named_from <= S.n); }
function linkify(text, self, chapter) {
  const {map, plain, re} = linker();
  text = String(text ?? '');
  if (!re) return esc(text);
  let out = '', last = 0;
  for (const m of text.matchAll(re)) {
    out += esc(text.slice(last, m.index));
    const id = map[m[0]];
    out += id === self || (plain[m[0]] && !plain[m[0]].has(chapter)) ? esc(m[0]) : `<a class="ent" data-ent="${id}" href="#${hashFor({p: 'e:' + id, tab: ''})}">${esc(m[0])}</a>`;
    last = m.index + m[0].length;
  }
  return out + esc(text.slice(last));
}
function properNames(text) {
  const link = linker();
  if (!link.ci) {
    const common = new Set();
    for (const t of [...until(D.chapters, 'n').map(c => c.synopsis), ...until(D.facts).map(f => f.claim)]) for (const w of t.match(/(?<![\p{L}\p{N}])\p{Ll}[\p{L}'-]*/gu) || []) common.add(w);
    const proper = name => name.split(/\s+/).some(w => /^\p{Lu}/u.test(w) && !common.has(w.toLowerCase()));
    const names = Object.keys(link.map).flatMap(n => [n, ...n.split(/\s+/).filter(w => w.length > 2)]).filter(proper);
    const keys = [...new Set(names)].sort((a, b) => b.length - a.length);
    link.cased = Object.fromEntries(keys.map(k => [k.toLowerCase(), k]));
    link.ci = keys.length ? new RegExp('(?<![\\p{L}\\p{N}])(' + keys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')(?![\\p{L}\\p{N}])', 'giu') : /$^/;
  }
  return text.replace(link.ci, m => link.cased[m.toLowerCase()] || m);
}

const wordSet = s => new Set(s.split(' '));
const WORDS = {
  aux: wordSet('is are was were be been being has have had can could will would may might must should does did'),
  adverb: wordSet('also formerly possibly previously once still now later secretly openly currently usually allegedly reportedly'),
  prep: wordSet('by of to in on at with from for into inside behind across after as about toward towards under over near against among between through within beside'),
  state: wordSet('located situated acquainted allied married engaged related connected associated devoted dedicated imprisoned confined trapped installed employed descended named known interested obsessed sealed stored hidden kept found based involved armed bound used written built suspected accused believed rumoured rumored thought feared expected assigned buried born hostile loyal indebted biased worth similar close responsible pregnant unrelated identical equal opposed wary afraid fond aware'),
  past: wordSet('overthrew sought repaid wrote stole saw made gave took held led met bought sold sent found lent built began became brought caught fought kept left lost paid told taught won ran rode slew swore struck spoke knew drew grew threw chose hid ate fell felt flew forgot forgave froze got hung heard hit hurt let lay meant put quit read said sat shot shut slept stood stuck swam tore woke awoke wore wove beat dug'),
  the: wordSet('main best only same first last sole eldest oldest youngest chief capital home head leader ruler founder king queen heir origin source author creator inventor designer owner captain commander master boss landlord mother father wife husband widow widower'),
  epithet: wordSet('suspected rumoured rumored alleged accused believed known presumed sworn'),
  det: wordSet('the a an his her its their my our your this that'),
  bond: wordSet('affair romance feud rivalry bond quarrel grudge pact truce debt'),
  number: wordSet('one two three four five six seven eight nine ten eleven twelve twenty hundred'),
};
const isNumber = w => /^\d+$/.test(w || '') || WORDS.number.has(w);
const isVerbS = w => /[a-z]s$/.test(w) && !/(ss|us|is)$/.test(w);
const article = w => /^(?:[aio]|e(?!u)|u(?![bcfhjklmnprstv][aeiou]))/.test(w) ? 'an' : 'a';
const verbish = w => isVerbS(w) || WORDS.past.has(w) || /ed$/.test(w || '');

function copula(words) {
  const [w, next] = words;
  if (WORDS.aux.has(w)) return '';
  if (next === 'by' && !isVerbS(w)) return 'is';
  if (WORDS.prep.has(w)) return 'is';
  if (WORDS.state.has(w) && (WORDS.prep.has(next) || WORDS.state.has(next) || isNumber(next))) return w === 'born' ? 'was' : 'is';
  if (verbish(w) && !(WORDS.epithet.has(w) && next && !WORDS.det.has(next))) return '';
  if (/ing$/.test(w)) return 'is';
  if (/(able|ible|ous|ful|less)$/.test(w)) return 'is';
  const at = words.findIndex(x => WORDS.prep.has(x));
  const head = words[at - 1];
  if (at > 0 && ['with', 'to', 'against'].includes(words[at]) && (WORDS.bond.has(head) || /(ship|ance|ence|ment|tion|sion|age)$/.test(head))) return 'has ' + article(w);
  if (WORDS.det.has(w) || isNumber(next) || w === 'part') return 'is';
  return WORDS.the.has(w) ? 'is the' : 'is ' + article(w);
}

function predicate(wording) {
  const all = String(wording).trim().split(/\s+/);
  const adverb = (w, i) => i < all.length - 1 && (WORDS.adverb.has(w) || /ly$/.test(w) && verbish(all[i + 1]));
  const lead = all.slice(0, all.findIndex((w, i) => !adverb(w, i)));
  const rest = all.slice(lead.length);
  const [verb, ...art] = copula(rest.map(w => w.toLowerCase())).split(' ').filter(Boolean);
  return properNames([verb, ...lead, ...art, ...rest].filter(Boolean).join(' '));
}

const chapterRefs = text => text.replace(/\(ch ?(\d+)\)/g, (m, n) => +n <= S.n ? `(<a ${goTo(`ch:${n}`)}>ch ${n}</a>)` : m);
const entLink = (id, among) => {
  id = live(id);
  const e = D.byId[id];
  return `<a class="ent" data-ent="${id}" href="#${hashFor({p: 'e:' + id, tab: ''})}">${esc(displayName(e, among))}</a>`;
};
const chLink = n => `<a ${goTo(`ch:${n}`)} class="chip">Ch ${n}</a>`;
const ctitle = n => (D.ch[n]?.title || '').replace(/^\d+\s*[:.]?\s*/, '');
const quotes = qs => (qs || []).map(q => `<blockquote>${esc(q)}</blockquote>`).join('');
let discs = 0;
const showHide = noun => `<span class="ifshut">Show</span><span class="ifopen">Hide</span> ${noun}`;
function expander(label, body) {
  const id = 'disc' + ++discs;
  return [`<button type="button" class="disc" aria-expanded="false" aria-controls="${id}"><span>${label}</span></button>`, `<div class="discbody" id="${id}" hidden>${body}</div>`];
}
function toggleDisc(btn) {
  const open = btn.getAttribute('aria-expanded') !== 'true';
  btn.setAttribute('aria-expanded', String(open));
  $(btn.getAttribute('aria-controls')).hidden = !open;
}
function expandRow(head, noun, body) {
  if (!body) return `<div class="fact">${head}</div>`;
  const [btn, panel] = expander(showHide(noun), body);
  return `<div class="fact">${head} ${btn}${panel}</div>`;
}
const quoteNoun = qs => (qs || []).length > 1 ? `${qs.length} quotes` : 'quote';
function expandHeading(title, body) {
  const [btn, panel] = expander(title, body);
  return `<h2>${btn}</h2>${panel}`;
}

const goTo = p => `data-go="${p}" href="#${esc(hashFor({p, tab: '', m: ''}))}"`;
const onPage = patch => patch.p && patch.p !== S.p ? {sort: '', ...patch} : patch;
function hashFor(patch) {
  const st = {...S, ...onPage(patch)};
  return new URLSearchParams(HASH_KEYS.filter(k => st[k] !== '' && st[k] != null).map(k => [k, st[k]])).toString();
}
function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  for (const k of HASH_KEYS) if (h.has(k)) S[k] = k === 'n' ? +h.get(k) : h.get(k);
  if (!h.has('n')) S.n = +store.get(D.storeKey) || 1;
  S.n = Math.min(Math.max(1, S.n || 1), D.book.max);
}
function writeHash() {
  history.replaceState(null, '', '#' + hashFor({}));
  store.set(D.storeKey, S.n);
}
function go(patch) {
  const page = patch.p && patch.p !== S.p;
  Object.assign(S, onPage(patch));
  if (page) { more = 60; Object.assign(G, {view: null, limit: STEP, open: new Set()}); }
  writeHash();
  render();
  if (page) window.scrollTo(0, 0);
}

function counts() {
  const c = {};
  for (const e of D.entities) if (full(e)) c[e.type] = (c[e.type] || 0) + 1;
  return c;
}

function renderSide(c) {
  const types = Object.keys(c).sort((a, b) => c[b] - c[a] || a.localeCompare(b));
  const qs = D.questions.map(qState);
  const vols = D.volumes.filter(v => v.from <= S.n);
  const item = (go, text, n) => `<a ${goTo(go)} class="${S.p === go ? 'on' : ''}">${esc(text)}${n != null ? ` <span>${n}</span>` : ''}</a>`;
  $('side').innerHTML = `<h4>Navigate</h4>${item('home', 'Home')}${item('chapters', 'Chapters', S.n)}${item('mysteries', 'Mysteries', qs.filter(x => x === 'open' || x === 'partial').length)}${item('graph', 'Graph')}`
    + (D.checks?.length ? item('checks', 'Needs checking', openChecks().length) : '')
    + (vols.length ? `<h4>Volumes</h4>${vols.map(v => item('v:' + v.id, v.name)).join('')}` : '')
    + `<h4>Categories</h4>${types.map(t => item('cat:' + t, catName(t), c[t])).join('')}`;
}

function chapterCard(c, full) {
  const text = D.book.text ? ` <a class="muted" href="text/${String(c.n).padStart(4, '0')}.txt" target="_blank" rel="noopener">read</a>` : '';
  return `<div class="ccard ${full ? 'full' : ''}"><div>${chLink(c.n)}${text}</div><h3><a ${goTo(`ch:${c.n}`)}>${esc(ctitle(c.n))}</a></h3><p>${linkify(c.synopsis, null, c.n)}</p></div>`;
}

function entRow(e, extra, among) {
  const l = lede(e);
  return `<li><span class="ch">Ch ${e.first}</span>${entLink(e.id, among)}<span class="badge">${esc(e.type)}</span>${extra || ''}<span class="sum">${esc(l.text)}</span></li>`;
}

const FEATURE = {pool: 12, leads: 6};
function featured() {
  const degree = {};
  for (const r of edgesAt()) if (r.role !== 'erased') for (const id of [r.source, r.target]) degree[id] = (degree[id] || 0) + 1;
  const people = D.entities.filter(e => e.type === 'character' && full(e) && degree[e.id] && lede(e).text);
  people.sort((a, b) => degree[b.id] - degree[a.id] || displayName(a).localeCompare(displayName(b)));
  const summed = people.filter(e => (e.summary && e.summary.chapter <= S.n) || until(e.summaries || []).length);
  const pool = (summed.length ? summed : people).slice(0, FEATURE.pool);
  return pool.length ? pool[S.n % pool.length] : null;
}

function portal() {
  const e = featured();
  const leads = D.questions.filter(q => qState(q) === 'partial').map(q => ({q, lead: until(q.leads).at(-1)}))
    .sort((a, b) => b.lead.chapter - a.lead.chapter || a.q.id.localeCompare(b.q.id)).slice(0, FEATURE.leads);
  const feature = e ? `<section class="panel feature"><h3>Featured entry</h3><h4>${entLink(e.id)}</h4><p>${linkify(clip(lede(e).text, 420), e.id, S.n)}</p><a ${goTo(`e:${e.id}`)}>Read the full entry</a></section>` : '';
  const ask = leads.length ? `<section class="panel"><h3>Questions with new leads</h3><ul class="plist">${leads.map(({q, lead}) => `<li><span>${linkify(q.question, null, q.chapter)}</span><span class="chip">lead ch ${lead.chapter}</span></li>`).join('')}</ul><a ${goTo('mysteries')}>All mysteries</a></section>` : '';
  return feature || ask ? `<div class="portal">${feature}${ask}</div>` : '';
}

function renderHome(c) {
  const types = Object.keys(c).sort((a, b) => c[b] - c[a] || a.localeCompare(b));
  const recent = D.entities.filter(full).sort((a, b) => b.first - a.first || a.name.localeCompare(b.name)).slice(0, 12);
  const qs = D.questions.map(qState);
  const chs = until(D.chapters, 'n').slice(-3).reverse();
  const vols = D.volumes.filter(v => v.from <= S.n);
  const intro = S.n === 1 && !store.get(D.storeKey + ':seen') ? `<div class="note">Set the slider to the chapter you have just finished. Nothing past it is shown anywhere on the site.</div>` : '';
  return `<div class="home"><h1>${esc(D.book.title)}</h1><div class="subtitle">Everything known up to chapter ${S.n}: ${esc(ctitle(S.n))}</div>${intro}
  <div class="stats"><div class="stat"><b>${D.entities.filter(full).length}</b>entries</div><div class="stat"><b>${visFactsAll()}</b>facts</div><div class="stat"><b>${qs.filter(x => x === 'open').length}</b>open mysteries</div><div class="stat"><b>${qs.filter(x => x === 'partial').length}</b>with leads</div><div class="stat"><b>${qs.filter(settled).length}</b>solved</div></div>
  ${portal()}
  <h2>Latest chapters</h2><div class="cards">${chs.map(ch => chapterCard(ch)).join('')}</div>
  ${vols.length ? `<h2>Volumes</h2><div class="cards">${vols.map(v => `<a class="ccard" ${goTo(`v:${v.id}`)}><div><span class="chip">Ch ${v.from} to ${v.to}</span></div><h3>${esc(v.name)}</h3><p>${S.n >= v.to ? 'Complete' : 'In progress'}</p></a>`).join('')}</div>` : ''}
  <h2>Categories</h2><div class="cats">${types.map(t => `<a class="cat" ${goTo(`cat:${t}`)}>${esc(catName(t))}<span>${c[t]}</span></a>`).join('')}</div>
  <h2>Recently introduced</h2><ul class="list">${recent.map(e => entRow(e)).join('')}</ul></div>`;
}
const mentionQuote = e => e.mention.quote ? `<blockquote>${esc(e.mention.quote)}</blockquote>` : '';
const ladderSteps = l => until(l.steps).filter(s => vis(D.byId[live(s.id)]));
const visLadders = () => D.ladders.filter(l => (l.group === null || vis(D.byId[live(l.group)])) && ladderSteps(l).length);
const ladderList = l => `<ul class="list">${ladderSteps(l).map(s => `<li><span class="ch">${esc(cap(D.book.ladder.step_type))} ${s.rank}</span>${entLink(s.id)}${chLink(s.chapter)}</li>`).join('')}</ul>`;

const catLink = t => `<a ${goTo(`cat:${esc(t)}`)}>${esc(catName(t))}</a>`;
const typeCrumbs = t => `<a ${goTo('home')}>Home</a>${D.parents[t] ? ` &rsaquo; ${catLink(D.parents[t])}` : ''}`;

const CAT = {az: 20, aliases: 2};
let catCache = {n: -1};
function catModel() {
  if (catCache.n === S.n) return catCache;
  const members = new Map(factionsAt('').groups.map(g => [g.id, g.members.length]));
  const within = new Map(), people = new Map();
  const walk = (p, up) => {
    if (up) within.set(p.id, up);
    people.set(p.id, p.people.length);
    p.children.forEach(k => walk(k, p.id));
  };
  placesAt().roots.forEach(p => walk(p, null));
  const rungs = new Map(), steps = new Map();
  for (const l of visLadders()) {
    const known = ladderSteps(l);
    if (l.group) steps.set(live(l.group), known.length);
    for (const st of known) if (!rungs.has(live(st.id))) rungs.set(live(st.id), {group: l.group && live(l.group), rank: st.rank});
  }
  catCache = {n: S.n, members, within, people, rungs, steps, seen: storyData().seen};
  return catCache;
}

const fieldCell = (e, key) => {
  const o = fieldSeen(key, e.profile?.fields[key] || []).at(-1);
  return o && {sort: o.value.toLowerCase(), html: linkify(cap(o.value), null, o.chapter)};
};
const countCell = (n, html = n) => n ? {sort: n, html} : null;
const linkCell = id => id && {sort: displayName(D.byId[id]), html: entLink(id)};
function nameCell(e) {
  const name = displayName(e, e.type), aka = visAliases(e).filter(a => a !== name);
  const more = aka.length > CAT.aliases ? ` +${aka.length - CAT.aliases}` : '';
  return {sort: name, html: entLink(e.id, e.type) + (aka.length ? `<span class="al">${aka.slice(0, CAT.aliases).map(esc).join(', ')}${more}</span>` : '')};
}
const CAT_COLS = [
  {key: 'name', label: () => 'Name', of: nameCell},
  {key: 'status', label: () => 'Status', of: e => { const st = e.profile && currentStatus(e.profile); return st && {sort: st.value, html: esc(cap(st.value))}; }},
  {key: 'affiliation', label: () => 'Affiliation', of: e => fieldCell(e, 'affiliation')},
  {key: 'occupation', label: () => 'Occupation', of: e => fieldCell(e, 'occupation')},
  {key: 'group', label: () => cap(D.book.ladder.group_type), of: (e, m) => linkCell(m.rungs.get(e.id)?.group)},
  {key: 'rank', label: () => 'Rank', num: true, of: (e, m) => { const r = m.rungs.get(e.id); return r && {sort: r.rank, html: esc(r.rank)}; }},
  {key: 'steps', label: () => cap(plural(D.book.ladder.step_type)), num: true, down: true, of: (e, m) => countCell(m.steps.get(e.id))},
  {key: 'members', label: () => 'Members', num: true, down: true, of: (e, m) => countCell(m.members.get(e.id), `<a ${goTo(factionRoute(e.id))}>${m.members.get(e.id)}</a>`)},
  {key: 'within', label: () => 'Located in', of: (e, m) => linkCell(m.within.get(e.id))},
  {key: 'people', label: () => 'People', num: true, down: true, of: (e, m) => countCell(m.people.get(e.id))},
  {key: 'first', label: () => 'First seen', num: true, of: e => ({sort: e.first, html: chLink(e.first)})},
  {key: 'last', label: () => 'Last seen', num: true, down: true, of: e => { const c = lastSeen(e); return {sort: c, html: chLink(c)}; }},
  {key: 'present', label: () => 'Chapters present', num: true, down: true, of: (e, m) => countCell(m.seen.get(e.id)?.size)},
  {key: 'facts', label: () => 'Facts', num: true, down: true, of: e => { const n = visFacts(e.id).length; return {sort: n, html: n}; }},
];

const cmpCell = (a, b) => typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b), undefined, {numeric: true, sensitivity: 'base'});
function catSort(cols) {
  const col = cols.find(c => c.key === S.sort.replace(/^-/, ''));
  return col ? {col, down: S.sort.startsWith('-')} : {col: cols[0], down: false};
}
function sortRows(rows, {col, down}) {
  const name = r => r.cells.name.sort;
  return rows.sort((x, y) => {
    const a = x.cells[col.key], b = y.cells[col.key];
    return (a && b ? (down ? -1 : 1) * cmpCell(a.sort, b.sort) : !a - !b) || cmpCell(name(x), name(y));
  });
}
const letterOf = name => {
  const c = name.normalize('NFD').replace(/[^\p{L}\p{N}]/gu, '').charAt(0).toUpperCase();
  return /[A-Z]/.test(c) ? c : 'other';
};
function sortHead(c, sort) {
  const on = sort.col === c;
  const next = (on ? !sort.down : c.down) ? '-' + c.key : c.key;
  const mark = on ? `<span class="sortmark" aria-hidden="true">${sort.down ? '&darr;' : '&uarr;'}</span>` : '';
  return `<th scope="col"${c.num ? ' class="num"' : ''}${on ? ` aria-sort="${sort.down ? 'descending' : 'ascending'}"` : ''}><a data-sort="${next}" href="#${esc(hashFor({sort: next}))}">${esc(c.label())}${mark}</a></th>`;
}
function catTable(rows, cols, sort, letters) {
  const cell = (r, c, i) => {
    const html = r.cells[c.key]?.html ?? '';
    return i ? `<td${c.num ? ' class="num"' : ''}>${html}</td>` : `<th scope="row">${html}</th>`;
  };
  const row = r => {
    const k = letters && letterOf(r.cells.name.sort), id = k && !letters.has(k) ? (letters.add(k), ` id="az-${k}"`) : '';
    return `<tr${id}>${cols.map((c, i) => cell(r, c, i)).join('')}</tr>`;
  };
  return `<div class="ctable"><table><thead><tr>${cols.map(c => sortHead(c, sort)).join('')}</tr></thead><tbody>${rows.map(row).join('')}</tbody></table></div>`;
}
function azBar(rows) {
  const have = new Set(rows.map(r => letterOf(r.cells.name.sort)));
  const keys = [...'ABCDEFGHIJKLMNOPQRSTUVWXYZ', ...(have.has('other') ? ['other'] : [])];
  const text = k => k === 'other' ? '#' : k;
  return `<nav class="az" aria-label="Jump to a letter">${keys.map(k => have.has(k) ? `<a data-az="${k}" href="#${esc(hashFor({sort: 'name'}))}">${text(k)}</a>` : `<span aria-hidden="true">${text(k)}</span>`).join('')}</nav>`;
}

function renderCat(type) {
  const byName = (a, b) => displayName(a, type).localeCompare(displayName(b, type));
  const es = D.entities.filter(e => full(e) && e.type === type).sort(byName);
  const minors = D.entities.filter(e => minor(e) && e.type === type).sort((a, b) => a.mention.chapter - b.mention.chapter || byName(a, b));
  const list = rows => `<ul class="list">${rows.map(e => entRow(e, `<span class="badge">${visFacts(e.id).length} facts</span>`, type)).join('')}</ul>`;
  const c = counts();
  const subs = D.typeOrder.filter(t => D.parents[t] === type && c[t]);
  const asList = S.tab === 'list';
  const views = `<nav class="pills" aria-label="Show as">${[['', 'Table'], ['list', 'List']].map(([k, t]) => `<a data-tab="${k}" href="#${esc(hashFor({tab: k}))}"${(k === 'list') === asList ? ' class="on" aria-current="true"' : ''}>${t}</a>`).join('')}</nav>`;
  let tools = views, named, unnamed;
  if (asList) [named, unnamed] = [list(es.filter(e => !unnamedAt(e))), list(es.filter(unnamedAt))];
  else {
    const m = catModel();
    const rows = es.map(e => ({e, cells: Object.fromEntries(CAT_COLS.map(col => [col.key, col.of(e, m) || null]))}));
    const cols = CAT_COLS.filter(col => col.key === 'name' || rows.some(r => r.cells[col.key]));
    const sort = catSort(cols);
    sortRows(rows, sort);
    const [mine, rest] = [rows.filter(r => !unnamedAt(r.e)), rows.filter(r => unnamedAt(r.e))];
    if (mine.length > CAT.az) tools += azBar(mine);
    named = mine.length ? catTable(mine, cols, sort, sort.col.key === 'name' && new Set()) : '';
    unnamed = rest.length ? catTable(rest, cols, sort) : '';
  }
  return `<div class="crumbs">${typeCrumbs(type)}</div><h1>${esc(catName(type))}</h1><div class="subtitle">${es.length} entries as of chapter ${S.n}</div>
  ${subs.length ? `<h2>Subcategories</h2><div class="cats">${subs.map(t => `<a class="cat" ${goTo(`cat:${esc(t)}`)}>${esc(catName(t))}<span>${c[t]}</span></a>`).join('')}</div>` : ''}
  ${es.length ? `<div class="ctools">${tools}</div>` : ''}${named}${es.some(unnamedAt) ? `<h2>Unnamed figures</h2>${unnamed}` : ''}
  ${type === D.book.ladder?.group_type && visLadders().length ? `<h2>Ladders</h2>${visLadders().map(l => `<div class="chgroup"><h4>${entLink(l.group, type)}</h4>${ladderList(l)}</div>`).join('')}` : ''}
  ${minors.length ? `<h2>Minor mentions</h2><ul class="list">${minors.map(e => `<li><span>${esc(displayName(e, type))}</span>${chLink(e.mention.chapter)}<span class="quote">${mentionQuote(e)}</span></li>`).join('')}</ul>` : ''}`;
}

const PER_TIMELINE = new Set(['status', 'affiliation', 'marital_status', 'occupation', 'residence']);
function currentStatus(profile) {
  const visible = until(profile.fields.status || []);
  const shown = visible.filter(o => role(o.timeline) === 'current');
  const erasedDeath = visible.filter(o => o.value === 'dead' && role(o.timeline) !== 'current' && D.tl[o.timeline]?.kind === 'run').at(-1)?.chapter;
  const distinct = [];
  for (const o of shown.slice().reverse()) if (!distinct.some(d => d.value === o.value)) distinct.push(o);
  const cur = shown.at(-1);
  const seen = (profile.spoke || []).filter(([c, tid]) => c <= S.n && role(tid) === 'current').map(([c]) => c);
  if (cur && !(cur.value === 'missing' && Math.max(0, ...seen) > cur.chapter)) return {value: cur.value, chapter: cur.chapter, basis: 'observed', earlier: distinct.slice(1), timeline: cur.timeline};
  const past = visible.filter(o => o.value === 'dead' && D.tl[o.timeline]?.kind === 'flashback').at(-1);
  if (past && past.chapter >= Math.max(0, ...seen)) return {value: 'dead', chapter: past.chapter, basis: 'past', earlier: [], timeline: past.timeline};
  if (seen.length) return {value: 'alive', chapter: Math.max(...seen), basis: 'spoke', earlier: [], erasedDeath};
  const present = (profile.appeared || []).filter(([c, tid]) => c <= S.n && role(tid) === 'current').map(([c]) => c);
  if (present.length) return {value: 'alive', chapter: Math.max(...present), basis: 'appeared', earlier: [], erasedDeath};
  if (erasedDeath) return {value: 'alive', chapter: erasedDeath, basis: 'erased_death', earlier: []};
  return null;
}
function statusRow(profile) {
  const s = currentStatus(profile);
  if (!s) return '';
  let cell;
  if (s.basis === 'erased_death') cell = `Alive <div class="prev">died only in an erased timeline (ch ${s.chapter})</div>`;
  else if (s.basis === 'spoke' || s.basis === 'appeared') cell = `Alive <span class="prev">(as of ch ${s.chapter}, inferred)</span>${s.erasedDeath ? `<div class="prev">died only in an erased timeline (ch ${s.erasedDeath})</div>` : ''}`;
  else cell = `${esc(cap(s.value))} <span class="prev">(ch ${s.chapter})</span>${tlBadge(s.timeline)}`;
  if (s.earlier.length) cell += `<div class="prev">previously ${s.earlier.map(o => `${esc(cap(o.value))} (ch ${o.chapter})`).join(', ')}</div>`;
  return `<tr><th>${esc(label('status'))}</th><td>${cell}</td></tr>`;
}
function fieldSeen(key, obs) {
  const current = until(obs).filter(o => role(o.timeline) === 'current');
  return current.length || PER_TIMELINE.has(key) ? current : until(obs);
}
function infoRows(profile) {
  if (!profile) return '';
  const fields = 'status' in profile.fields ? profile.fields : {status: [], ...profile.fields};
  return Object.entries(fields).map(([key, obs]) => {
    if (key === 'status') return statusRow(profile);
    const seen = fieldSeen(key, obs);
    if (!seen.length) return '';
    const cur = seen.at(-1);
    const prev = [];
    for (const o of seen.slice(0, -1).reverse()) {
      if (o.value.toLowerCase() !== cur.value.toLowerCase() && !prev.some(p => p.value.toLowerCase() === o.value.toLowerCase())) prev.push(o);
    }
    return `<tr><th>${esc(label(key))}</th><td>${linkify(cap(cur.value), null, cur.chapter)} <span class="prev">(ch ${cur.chapter})</span>${tlBadge(cur.timeline)}${prev.length ? `<div class="prev">previously ${prev.map(o => `${esc(cap(o.value))} (ch ${o.chapter})`).join(', ')}</div>` : ''}</td></tr>`;
  }).join('');
}

function obsList(obs, self) {
  return obs.map(o => expandRow(`${linkify(o.value, self, o.chapter)} ${chLink(o.chapter)}${tlBadge(o.timeline)}`, quoteNoun(o.quotes), quotes(o.quotes))).join('');
}

const sectionHead = (key, title) => `<h3 id="sec-${key}" tabindex="-1">${title}</h3>`;
const section = (key, title, body) => ({key, title, html: sectionHead(key, title) + body});

function historySection(e) {
  const arcs = until(e.history || []);
  return arcs.length ? [section('history', 'History', arcs.map(h => `<div class="chgroup"><h4><span class="chip">Ch ${h.start} to ${h.end}</span> ${esc(h.arc)}</h4><div class="prose"><p>${chapterRefs(linkify(h.text, e.id))}</p></div></div>`).join(''))] : [];
}

function writtenSection(e, key, title, observations, paragraphs) {
  const evidence = until(observations || []);
  const para = latest(paragraphs || []);
  if (para) return [section(key, title, `<div class="prose"><p>${chapterRefs(linkify(para.text, e.id))}</p></div><div class="asof">Written from evidence up to chapter ${para.chapter}</div>${evidence.length ? expander(showHide(`the evidence (${evidence.length})`), obsList(evidence, e.id)).join('') : ''}`)];
  return evidence.length ? [section(key, title, obsList(evidence, e.id))] : [];
}

function profileSections(e) {
  const p = e.profile;
  if (!p) return historySection(e);
  const out = [];
  out.push(...writtenSection(e, 'appearance', 'Appearance', p.lists.appearance, p.appearance));
  out.push(...writtenSection(e, 'personality', 'Personality', p.lists.personality_evidence, p.personality));
  out.push(...historySection(e));
  const trivia = until(p.lists.trivia || []);
  if (trivia.length) out.push(section('trivia', 'Trivia', obsList(trivia, e.id)));
  return out;
}

const TOC = {least: 5};
function contentsList(items) {
  const link = ([key, title, tab]) => `<a data-sec="${key}" data-in="${tab}" href="#${esc(hashFor(tab ? {tab} : {}))}">${title}</a>`;
  return items.length < TOC.least ? '' : `<nav class="toc" aria-label="Contents">${items.map(link).join('')}</nav>`;
}

function factBadge(f) {
  const tl = tlBadge(f.timeline);
  if (f.status === 'belief') return `<span class="badge belief">${esc(f.by)} believes</span>${tl}`;
  if (f.status && f.status !== 'stated') return `<span class="badge">${esc(f.status)}</span>${tl}`;
  return tl;
}
const factRow = (f, id) => expandRow(`${linkify(f.claim, id, f.chapter)}${factBadge(f)}`, f.quotes?.length ? quoteNoun(f.quotes) : 'source',
  `${quotes(f.quotes)}<div class="qmeta">${f.by === 'narrator' ? 'Narrator' : 'According to ' + esc(f.by)}${f.unverified ? ', quote not found in the chapter' : ''}</div>`);
const wordKey = s => String(s ?? '').toLowerCase().replace(/_/g, ' ').replace(/\s+/g, ' ').replace(/^[\s.,;:!?"']+|[\s.,;:!?"']+$/g, '');
const tieKey = (source, target, r, rl) => [source, target, wordKey(r.type), wordKey(r.detail), rl === 'current' ? '' : r.timeline, r.status, r.by].join('|');
const wording = r => r.detail ? `${r.label ?? r.type} ${r.detail}` : r.label ?? r.type;
const detailHtml = (r, chapter) => r.detail ? ` <span class="rdetail">${linkify(r.detail, null, chapter)}</span>` : '';
const relRow = (r, id, name) => expandRow(`${r.source === id ? esc(name) : entLink(r.source)} <span class="rt">${esc(predicate(r.type))}</span> ${r.target === id ? esc(name) : entLink(r.target)}${detailHtml(r, r.chapter)} ${(r.chapters || [r.chapter]).map(chLink).join(' ')}${beliefBadge(r)}${tlBadge(r.timeline)}`,
  quoteNoun(r.quotes), quotes(r.quotes));
function groupRels(rows) {
  const by = new Map();
  for (const r of rows) {
    const key = tieKey(r.source, r.target, r, role(r.timeline));
    const g = by.get(key);
    if (!g) by.set(key, {...r, chapters: [r.chapter], quotes: [...(r.quotes || [])]});
    else {
      if (!g.chapters.includes(r.chapter)) g.chapters.push(r.chapter);
      for (const q of r.quotes || []) if (!g.quotes.includes(q)) g.quotes.push(q);
    }
  }
  return [...by.values()];
}

function erasedSection(fs, rels, id, name) {
  const by = {};
  for (const x of [...fs, ...rels]) (by[x.timeline] ||= []).push(x);
  const ids = Object.keys(by).sort((a, b) => D.tl[a].started - D.tl[b].started);
  if (!ids.length) return '';
  return `<h3>In erased timelines</h3>` + ids.map(t => `<div class="chgroup"><h4>${tlName(D.tl[t])} <span class="chip">Ch ${D.tl[t].started} to ${D.tl[t].erased}</span></h4>${by[t].map(x => x.claim ? factRow(x, id) : relRow(x, id, name)).join('')}</div>`).join('');
}

const lastSeen = e => Math.max(e.first, ...[...visFacts(e.id), ...visRels(e.id)].filter(r => role(r.timeline) !== 'erased').map(r => r.chapter));

function renderEntity(id) {
  id = live(id);
  const e = D.byId[id];
  if (!vis(e)) return `<h1>Not yet introduced</h1><p class="muted">This entry first appears after chapter ${S.n}. Move the slider forward to reveal it.</p>`;
  const crumbs = `<div class="crumbs">${typeCrumbs(e.type)} &rsaquo; ${catLink(e.type)}</div>`;
  if (minor(e)) return `<article class="entity"><div class="ehead">${crumbs}<h1>${esc(displayName(e))}</h1><div class="subtitle">${esc(cap(e.type))} &middot; a minor mention in ${chLink(e.mention.chapter)}</div></div>
    ${mentionQuote(e)}<p class="muted">Nothing more is known about this entry by chapter ${S.n}.</p></article>`;
  const name = displayName(e);
  const allFs = visFacts(id);
  const allRels = visRels(id);
  const fs = allFs.filter(f => role(f.timeline) !== 'erased');
  const rels = groupRels(allRels.filter(r => role(r.timeline) !== 'erased'));
  const xFs = allFs.filter(f => role(f.timeline) === 'erased');
  const xRels = groupRels(allRels.filter(r => role(r.timeline) === 'erased'));
  const names = visNames(e);
  const qs = D.questions.filter(q => qState(q) && names.some(t => q.question.includes(t) || q.quote?.includes(t)));
  const parts = profileSections(e);
  const profile = parts.map(x => x.html).join('');
  const groups = {};
  for (const f of fs) (groups[f.chapter] ||= []).push(f);
  const chs = Object.keys(groups).map(Number).sort((a, b) => b - a);
  const aliases = visAliases(e).filter(a => a !== name);
  const l = lede(e);
  const ladder = visLadders().find(l => live(l.group) === id);
  const leads = until(e.possibly || []).filter(p => vis(D.byId[live(p.id)])).map(p => `<div class="note">Possibly ${entLink(p.id)} (implied, ch ${p.chapter})${quotes(p.quote ? [p.quote] : [])}</div>`).join('');
  const tabs = [profile && ['profile', 'Profile'], ['facts', `Facts (${fs.length + xFs.length})`], ['relations', `Relations (${rels.length + xRels.length})`], ['mysteries', `Mysteries (${qs.length})`]].filter(Boolean);
  const tab = tabs.some(([k]) => k === S.tab) ? S.tab : tabs[0][0];
  const ego = egoPanel(id);
  const contents = contentsList([l.text && ['summary', 'Summary', ''], ladder && ['ladder', 'Ladder', ''], ego && ['connections', 'Connections', ''],
    ...parts.map(x => [x.key, x.title, 'profile']),
    ...[['facts', 'Facts', fs.length + xFs.length], ['relations', 'Relations', rels.length + xRels.length], ['mysteries', 'Mysteries', qs.length]].filter(t => t[2]).map(([k, t]) => ['tabs', t, k])].filter(Boolean));
  const infobox = `<aside class="infobox"><h3>${esc(name)}</h3><table>
    <tr><th>Type</th><td>${esc(cap(e.type))}</td></tr>
    ${aliases.length ? `<tr><th>Also known as</th><td>${aliases.map(esc).join('<br>')}</td></tr>` : ''}
    ${infoRows(e.profile)}
    <tr><th>First seen</th><td>Ch ${e.first}: ${esc(ctitle(e.first))}</td></tr>
    <tr><th>Last seen</th><td>Ch ${lastSeen(e)}</td></tr>
    <tr><th>Facts</th><td>${fs.length} in ${chs.length} chapters</td></tr>
    </table></aside>`;
  let body;
  if (tab === 'profile') body = `<div class="section">${profile}</div>`;
  else if (tab === 'facts') body = (chs.length ? chs.map(c => `<div class="chgroup"><h4>${chLink(c)} ${esc(ctitle(c))}</h4>${groups[c].map(f => factRow(f, id)).join('')}</div>`).join('') : xFs.length ? '' : '<p class="muted">No facts recorded yet.</p>') + erasedSection(xFs, [], id, name);
  else if (tab === 'relations') body = (rels.length ? `<div class="chgroup">${rels.slice().reverse().map(r => relRow(r, id, name)).join('')}</div>` : xRels.length ? '' : '<p class="muted">No relations recorded yet.</p>') + erasedSection([], xRels, id, name);
  else body = qs.length ? qs.map(mystCard).join('') : '<p class="muted">No mysteries mention this entry yet.</p>';
  return `<article class="entity">
    <div class="ehead">${crumbs}<h1>${esc(name)}</h1><div class="subtitle">${esc(cap(e.type))} &middot; first appears in chapter ${e.first}</div>${contents}</div>
    ${infobox}
    <div class="lede" id="sec-summary" tabindex="-1"><p>${linkify(l.text, id, l.chapter) || '<span class="muted">Nothing known yet.</span>'}</p>${l.chapter ? `<div class="asof">As understood at chapter ${l.chapter}</div>` : ''}${leads}${ladder ? `${sectionHead('ladder', 'Ladder')}${ladderList(ladder)}` : ''}${ego}</div>
    <nav class="tabs" id="sec-tabs" tabindex="-1">${tabs.map(([k, t]) => `<a data-tab="${k}" href="#${esc(hashFor({tab: k}))}" class="${tab === k ? 'on' : ''}">${t}</a>`).join('')}</nav>
    <div class="ebody">${body}</div></article>`;
}

const MYST_STATES = {open: 'Open', partial: 'Has leads', resolved: 'Resolved', 'premise-false': 'Premise does not hold', dropped: 'Loose end'};
const cited = rows => rows.map(r => `<div class="mlead"><div class="mlbl">${chLink(r.chapter)}</div><blockquote>${esc(r.quote)}</blockquote></div>`).join('');
const verdict = (label, text, rest) => `<div class="mans"><div class="mlbl">${label}</div><div>${text}</div>${rest}</div>`;
function mystCard(q) {
  const st = qState(q);
  const leads = until(q.leads);
  const end = endOf(q);
  const ask = `<div class="mq"><div class="mlbl">Question &middot; raised in ${chLink(q.chapter)}</div><div class="qq">${linkify(q.question, null, q.chapter)}${tlBadge(q.timeline)}</div>`
    + `${q.quote ? `<blockquote>${esc(q.quote)}</blockquote>` : ''}${end && ENDINGS[end] && st !== 'dropped' ? `<div class="qmeta">${ENDINGS[end]}</div>` : ''}</div>`;
  let answer = '';
  if (st === 'premise-false') {
    answer = verdict(`Premise does not hold &middot; ch ${q.premise.chapter}`, linkify(q.premise.explanation, null, q.premise.chapter), cited(q.premise.quotes || []));
  } else if (end === 'answered-implicitly' && !q.resolved) {
    answer = verdict('Answer &middot; from the story as a whole', linkify(q.ending.answer), cited(q.ending.quotes));
  } else if (st === 'resolved') {
    const payoff = q.resolved.payoff ? expander(showHide('how it pays off'), `<div class="prose"><p>${linkify(q.resolved.payoff, null, q.resolved.chapter)}</p></div>`).join('') : '';
    answer = verdict(`Answer &middot; resolved in ${chLink(q.resolved.chapter)}`, linkify(q.resolved.answer, null, q.resolved.chapter), `${q.resolved.quote ? `<blockquote>${esc(q.resolved.quote)}</blockquote>` : ''}${payoff}`);
  } else if (st === 'dropped') {
    answer = verdict(`Loose end &middot; ${ENDINGS[end].toLowerCase()} by ch ${q.ending.chapter}`, linkify(q.ending.reason || ''), '');
  }
  const leadRows = st === 'resolved' || st === 'premise-false' ? '' : leads.map(l => `<div class="mlead"><div class="mlbl">Lead &middot; ${chLink(l.chapter)}</div>${linkify(l.text, null, l.chapter)}${l.quote ? `<blockquote>${esc(l.quote)}</blockquote>` : ''}</div>`).join('');
  return `<div class="myst ${st}"><div class="mstate">${MYST_STATES[st]}</div>${ask}${leadRows}${answer}</div>`;
}

function renderMysteries() {
  const ended = D.questions.some(endOf);
  const by = {...(ended ? {end: []} : {}), open: [], partial: [], resolved: []};
  const dropped = [];
  for (const q of D.questions) { const st = qState(q); if (st === 'dropped') dropped.push(q); else if (st) by[settled(st) ? 'resolved' : st].push(q); }
  by.open.sort((a, b) => b.chapter - a.chapter);
  by.partial.sort((a, b) => until(b.leads).at(-1).chapter - until(a.leads).at(-1).chapter);
  const solvedAt = q => refuted(q) ? q.premise.chapter : q.resolved?.chapter ?? q.ending.chapter;
  by.resolved.sort((a, b) => solvedAt(b) - solvedAt(a));
  const answered = by.resolved.filter(atEnd);
  const mysteries = [...by.open, ...by.partial].sort((a, b) => (endOf(a) !== 'left-open') - (endOf(b) !== 'left-open') || b.chapter - a.chapter);
  if (ended) by.end = [...answered, ...mysteries, ...dropped];
  const m = by[S.m] ? S.m : ended ? 'end' : 'open';
  const show = by[m];
  const names = {end: 'End of book', open: 'Open', partial: 'Leads', resolved: 'Resolved'};
  const head = `<div class="crumbs"><a ${goTo('home')}>Home</a></div><h1>Mysteries</h1><div class="subtitle">Questions the story has raised by chapter ${S.n}</div>
  <div class="pills">${Object.keys(by).map(k => `<a data-m="${k}" href="#${esc(hashFor({m: k}))}" class="${m === k ? 'on' : ''}">${names[k]} (${by[k].length})</a>`).join('')}</div>`;
  if (m === 'end') return head + `<h2>Answered at the end (${answered.length})</h2>${answered.map(mystCard).join('')}<h2>Open mysteries (${mysteries.length})</h2>${mysteries.map(mystCard).join('')}`
    + expandHeading(`Loose ends (${dropped.length})`, dropped.map(mystCard).join(''));
  if (m === 'resolved') return head + show.slice(0, more).map(mystCard).join('') + (show.length > more ? `<button class="more" data-more>Show more (${show.length - more} left)</button>` : '');
  return head + Object.keys(TIERS).map(t => {
    const qs = show.filter(q => tierOf(q) === t);
    if (!qs.length) return '';
    const cards = qs.map(mystCard).join('');
    return t === 'cliffhanger' ? expandHeading(`${TIERS[t]} (${qs.length})`, cards) : `<h2>${TIERS[t]} (${qs.length})</h2>${cards}`;
  }).join('');
}

function timelineList() {
  const ts = (D.timelines || []).filter(t => t.kind !== 'main' && t.started <= S.n);
  if (!ts.length) return '';
  return `<h2>Timelines</h2><ul class="list">${ts.map(t => `<li><span class="ch">Ch ${t.started}</span><span>${tlName(t)}</span><span class="badge">${esc(t.kind)}</span>${role(t.id) === 'erased' ? `<span class="badge erased">erased in ch ${t.erased}</span>` : ''}</li>`).join('')}</ul>`;
}

function renderChapters() {
  const chs = until(D.chapters, 'n').slice().reverse();
  return `<div class="crumbs"><a ${goTo('home')}>Home</a></div><h1>Chapters</h1><div class="subtitle">Synopses of chapters 1 to ${S.n}</div>${timelineList()}
  <div class="cards">${chs.slice(0, more).map(c => chapterCard(c)).join('')}</div>${chs.length > more ? `<button class="more" data-more>Show more (${chs.length - more} left)</button>` : ''}`;
}

function renderChapter(n) {
  n = +n;
  const c = D.ch[n];
  if (!c || n > S.n) return `<h1>Chapter ${n}</h1><p class="muted">This chapter is past chapter ${S.n}. Move the slider forward to read its synopsis.</p>`;
  const intro = D.entities.filter(e => e.first === n && !minor(e));
  const raised = D.questions.filter(q => q.chapter === n);
  const answered = D.questions.filter(q => q.resolved?.chapter === n && solved(q));
  const facts = D.facts.filter(f => f.chapter === n);
  const byEnt = {};
  for (const f of facts) (byEnt[f.entity] ||= []).push(f);
  const nav = `<div class="pills">${n > 1 ? `<a ${goTo(`ch:${n - 1}`)}>&lsaquo; Ch ${n - 1}</a>` : ''}<a ${goTo('chapters')}>All chapters</a>${n < S.n ? `<a ${goTo(`ch:${n + 1}`)}>Ch ${n + 1} &rsaquo;</a>` : ''}</div>`;
  return `<div class="crumbs"><a ${goTo('home')}>Home</a> &rsaquo; <a ${goTo('chapters')}>Chapters</a></div><h1>${esc(ctitle(n))}</h1><div class="subtitle">Chapter ${n}</div>${nav}
  ${chapterCard(c, true)}
  ${intro.length ? `<h2>Introduced</h2><ul class="list">${intro.map(e => entRow(e)).join('')}</ul>` : ''}
  ${answered.length ? `<h2>Mysteries resolved</h2>${answered.map(mystCard).join('')}` : ''}
  ${raised.length ? `<h2>Mysteries raised</h2>${raised.map(mystCard).join('')}` : ''}
  ${facts.length ? `<h2>Facts learned</h2>${Object.entries(byEnt).map(([id, fs]) => `<div class="chgroup"><h4>${entLink(id)}</h4>${fs.map(f => expandRow(`${linkify(f.claim, id, f.chapter)}${factBadge(f)}`, quoteNoun(f.quotes), quotes(f.quotes))).join('')}</div>`).join('')}` : ''}`;
}

function renderVolume(id) {
  const v = D.volumes.find(x => x.id === id);
  if (!v || v.from > S.n) return `<h1>Volume</h1><p class="muted">This volume starts after chapter ${S.n}.</p>`;
  const done = S.n >= v.to;
  const arcs = v.arcs.filter(a => a.start <= S.n);
  const events = until(v.key_events);
  const deaths = until(v.deaths);
  const intro = D.entities.filter(e => e.first >= v.from && e.first <= Math.min(v.to, S.n) && !minor(e));
  const chars = intro.filter(e => e.type === 'character');
  const powers = intro.filter(e => D.power.has(e.type));
  const arcHtml = arcs.map(a => {
    if (a.end <= S.n) return `<div class="chgroup"><h4><span class="chip">Ch ${a.start} to ${a.end}</span> ${esc(a.name)}</h4><div class="prose">${a.summary.split(/\n\s*\n/).map(p => `<p>${linkify(p)}</p>`).join('')}</div></div>`;
    const sofar = D.chapters.filter(c => c.n >= a.start && c.n <= S.n);
    return `<div class="chgroup"><h4><span class="chip">Ch ${a.start} to ${S.n}</span> Current arc</h4><div class="note">You are in the middle of this arc. Its summary unlocks at chapter ${a.end}. Chapter synopses so far:</div>${sofar.map(c => `<p>${chLink(c.n)} ${linkify(c.synopsis, null, c.n)}</p>`).join('')}</div>`;
  }).join('');
  return `<div class="crumbs"><a ${goTo('home')}>Home</a></div><h1>${esc(v.name)}</h1><div class="subtitle">Chapters ${v.from} to ${v.to}${done ? '' : ` &middot; read up to ${S.n}`}</div>
  ${done && v.overview ? `<h2>Overview</h2><div class="prose"><p>${linkify(v.overview)}</p></div>` : `<div class="note">The volume overview and character arcs unlock when you finish chapter ${v.to}.</div>`}
  <h2>Plot by arc</h2>${arcHtml}
  ${events.length ? `<h2>Key events</h2><ul class="list">${events.map(k => `<li><span class="ch">${k.chapters.map(c => 'Ch ' + c).join(', ')}</span><span>${linkify(k.event, null, k.chapters[0])}</span></li>`).join('')}</ul>` : ''}
  ${done && v.development.length ? `<h2>Character development</h2>${v.development.map(d => `<div class="chgroup"><h4>${linkify(d.character)}</h4><div class="prose"><p>${linkify(d.development)}</p></div></div>`).join('')}` : ''}
  ${deaths.length ? `<h2>Deaths</h2>${deaths.map(d => expandRow(`${linkify(d.name, null, d.chapter)} ${chLink(d.chapter)}`, 'what happened', `<div class="prose"><p>${linkify(d.circumstances, null, d.chapter)}</p></div>${quotes(d.quotes)}${until(d.later || []).map(l => `<div class="prose"><p>${chLink(l.chapter)} ${linkify(l.circumstances, null, l.chapter)}</p></div>${quotes(l.quotes)}`).join('')}`)).join('')}` : ''}
  ${chars.length ? `<h2>Characters introduced</h2><ul class="list">${chars.map(e => entRow(e)).join('')}</ul>` : ''}
  ${powers.length ? `<h2>World introduced</h2><ul class="list">${powers.map(e => entRow(e)).join('')}</ul>` : ''}`;
}

const REL_GROUPS = [
  {key: 'kin', label: 'Family', says: 'blood or legal family: parent, child, sibling, cousin, heir'},
  {key: 'romance', label: 'Romance', says: 'marriage, courtship, love, a lover or former partner'},
  {key: 'alliance', label: 'Allies', says: 'friend, ally, colleague, companion, helper, acquaintance'},
  {key: 'teaching', label: 'Teaching', says: 'mentor and student, teacher, apprentice'},
  {key: 'service', label: 'Service', says: 'employer and employee, servant, agent, commander and subordinate'},
  {key: 'hostility', label: 'Hostility', says: 'enemy, rival, attacker, killer, captor'},
  {key: 'investigation', label: 'Investigation', says: 'one suspects, questions, follows, or spies on the other'},
  {key: 'membership', label: 'Membership', says: 'member, leader, or founder of a group'},
  {key: 'faith', label: 'Faith', says: 'worship, belief in a deity, clergy of a church'},
  {key: 'place', label: 'Places', says: 'where someone or something is, lives, or goes'},
  {key: 'ownership', label: 'Belongings', says: 'owning, holding, making, or using a thing'},
  {key: 'kind', label: 'Kinds and ranks', says: 'a kind, rank, stage, or other name of something'},
  {key: 'other', label: 'Other', says: 'a tie of no kind above'},
].map(g => ({...g, fams: [g.key]}));
const SECTORS = [
  {key: 'close', fams: ['kin', 'romance']},
  {key: 'allies', fams: ['alliance', 'service', 'teaching']},
  {key: 'conflict', fams: ['hostility', 'investigation']},
  {key: 'belong', fams: ['membership', 'faith']},
  {key: 'things', fams: ['ownership', 'place', 'kind', 'other']},
];
const SECTOR_OF = Object.fromEntries(SECTORS.flatMap(s => s.fams.map(f => [f, s.key])));
const groupOf = fam => REL_GROUPS.some(g => g.key === fam) ? fam : 'other';
const sectorFor = fam => SECTOR_OF[groupOf(fam)];
const swatch = group => `<i class="swatch" style="background:var(--r-${group})"></i>`;
function pairGroup(rows) {
  const count = {}, last = {};
  for (const r of rows) {
    if (r.family === 'other') continue;
    const g = groupOf(r.family);
    count[g] = (count[g] || 0) + r.chapters.length;
    last[g] = Math.max(last[g] || 0, ...r.chapters);
  }
  const close = Object.keys(count).filter(g => sectorFor(g) === 'close');
  return (close.length ? close : Object.keys(count)).sort((x, y) => count[y] - count[x] || last[y] - last[x])[0] || 'other';
}
function kindNow(rows) {
  const told = rows.filter(r => r.family !== 'other'), now = told.filter(r => r.role === 'current');
  const pool = now.length ? now : told, last = Math.max(...pool.flatMap(r => r.chapters));
  return pairGroup(pool.filter(r => r.chapters.includes(last)));
}
function tieHistory(rows) {
  const first = new Map();
  for (const r of rows) for (const c of r.chapters) if (!(first.get(wording(r)) <= c)) first.set(wording(r), c);
  return new Set(first.values()).size > 1 ? [...first].sort((a, b) => a[1] - b[1]).map(([kind, c]) => `ch ${c} ${kind}`).join(' · ') : '';
}
const TYPE_GROUPS = [
  {key: 'people', label: 'People', types: ['character']},
  {key: 'groups', label: 'Groups', types: ['organization']},
  {key: 'places', label: 'Places', types: ['place']},
  {key: 'things', label: 'Things', types: ['artifact']},
  {key: 'lore', label: 'Lore', types: ['concept', 'event', 'deity', 'creature', 'uncategorized']},
];
const kindOf = t => D.parents[t] || t;
const groupTypes = g => g.key === 'lore' ? D.typeOrder.filter(t => !TYPE_GROUPS.some(o => o !== g && o.types.includes(kindOf(t))))
  : [...g.types.filter(t => D.typeOrder.includes(t)), ...D.typeOrder.filter(t => D.parents[t] && g.types.includes(D.parents[t]))];

const peopleFirst = () => D.typeOrder.includes('character') ? ['character'] : D.typeOrder.slice(0, 1);
const GRAPH_VIEWS = {
  characters: {label: 'Characters', route: 'graph', tab: true, types: peopleFirst},
  all: {label: 'Whole book', route: 'graph:all', types: peopleFirst},
  path: {label: 'Connected?', route: 'graph:path', tab: true, types: () => D.typeOrder},
  story: {label: 'Storyline', route: 'graph:story', tab: true, types: () => ['character']},
  matrix: {label: 'Matrix', route: 'graph:matrix', tab: true, types: () => ['character']},
  factions: {label: 'Factions', route: 'graph:factions', tab: true, when: () => orgTypes().size > 0, types: () => []},
  ladder: {label: 'Power ladder', route: 'graph:ladder', tab: true, when: () => !!D.book.ladder && D.ladders.length > 0, types: () => []},
  family: {label: 'Family', route: 'graph:family', tab: true, when: () => familyAt().families.length > 0, types: () => []},
  places: {label: 'Places', route: 'graph:places', tab: true, when: () => placesAt().roots.length > 0, types: () => []},
  masks: {label: 'Disguises', route: 'graph:masks', tab: true, when: () => masksAt().wearers.length > 0, types: () => []},
};
const STEP = 20;
const G = {types: {}, hideFams: new Set(), erased: false, isolates: false, allTies: false, limit: STEP, open: new Set(), view: null, cam: null, shown: null, click: null, model: null, story: {add: new Set(), drop: new Set(), col: null, center: null, n: 0}};
let edgeCache = {n: -1};
const shownTypes = view => G.types[view] ||= new Set(GRAPH_VIEWS[view].types());

function edgesAt() {
  if (edgeCache.n === S.n) return edgeCache.rows;
  const by = new Map();
  for (const r of until(D.relations)) {
    const source = live(r.source), target = live(r.target);
    if (source === target || !vis(D.byId[source]) || !vis(D.byId[target])) continue;
    const rl = role(r.timeline);
    const key = tieKey(source, target, r, rl);
    const said = r.unverified ? [] : r.quotes || [];
    const g = by.get(key);
    if (g) {
      if (!g.chapters.includes(r.chapter)) g.chapters.push(r.chapter);
      for (const q of said) if (!g.quotes.includes(q)) g.quotes.push(q);
      continue;
    }
    const badge = rl === 'erased' ? 'erased timeline' : rl === 'aside' ? D.tl[r.timeline].kind : '';
    by.set(key, {source, target, label: r.type, detail: r.detail || '', family: r.family || 'other', role: rl, badge, status: r.status, by: r.by, chapters: [r.chapter], quotes: [...said]});
  }
  edgeCache = {n: S.n, rows: [...by.values()]};
  return edgeCache.rows;
}

function holderName(by) {
  if (!by || by === 'narrator') return '';
  if (!D.namesakes[by]) return by;
  const e = D.namesakes[by].map(id => D.byId[live(id)]).find(vis);
  return e ? displayName(e) : '';
}
const suspicion = r => r.status === 'belief' && holderName(r.by) ? `suspected by ${holderName(r.by)}` : '';
const beliefBadge = r => suspicion(r) ? ` <span class="badge belief">${esc(suspicion(r))}</span>` : '';

function ties() {
  if (edgeCache.partners) return edgeCache;
  const partners = new Map(), orgs = new Map();
  const add = (map, k, v) => (map.get(k) || map.set(k, new Set()).get(k)).add(v);
  for (const r of edgesAt()) {
    if (r.role === 'erased') continue;
    for (const [x, y] of [[r.source, r.target], [r.target, r.source]]) {
      add(partners, x, y);
      if (r.family === 'membership' && kindOf(D.byId[y].type) === 'organization' && kindOf(D.byId[x].type) !== 'organization') add(orgs, x, y);
    }
  }
  return Object.assign(edgeCache, {partners: new Map([...partners].map(([k, v]) => [k, v.size])), orgs});
}

function mainCharacter() {
  const degree = {};
  for (const r of edgesAt()) if (r.role !== 'erased') for (const id of [r.source, r.target]) degree[id] = (degree[id] || 0) + 1;
  const people = D.entities.filter(e => e.type === 'character' && vis(e) && degree[e.id]);
  people.sort((a, b) => degree[b.id] - degree[a.id] || displayName(a).localeCompare(displayName(b)));
  return people[0]?.id ?? null;
}

function graphFocus(arg, fallback = mainCharacter) {
  const picked = arg || store.get('graph-focus');
  return picked && full(D.byId[live(picked)]) ? live(picked) : fallback();
}

const drawnRows = () => edgesAt().filter(r => (G.erased || r.role !== 'erased') && !G.hideFams.has(r.family));
const byName = (a, b) => displayName(D.byId[a]).localeCompare(displayName(D.byId[b]));

function graphAt(arg) {
  if (/^path(:|$)/.test(arg || '')) return pathAt(arg.slice(5));
  if (/^story(:|$)/.test(arg || '')) return storyAt(arg.slice(6));
  if (/^matrix(:|$)/.test(arg || '')) return matrixAt();
  if (/^factions(:|$)/.test(arg || '')) return factionsAt(arg.slice(9));
  if (/^ladder(:|$)/.test(arg || '')) return ladderAt(arg.slice(7));
  if (/^family(:|$)/.test(arg || '')) return familyAt();
  if (/^places(:|$)/.test(arg || '')) return placesAt();
  if (/^masks(:|$)/.test(arg || '')) return masksAt();
  if (/^all(:|$)/.test(arg || '')) return wholeAt(arg.slice(4));
  return egoAt(graphFocus(arg));
}

const ROUTES = 3;
const pairRoute = (a, b) => `graph:path:${a || ''}~${b || ''}`;
const isPerson = id => TYPE_GROUPS.find(g => g.key === 'people').types.includes(D.byId[id].type);

function connect(from, to, hops) {
  const adj = new Map();
  for (const l of linksOf(drawnRows())) for (const [x, y] of [[l.a, l.b], [l.b, l.a]]) (adj.get(x) || adj.set(x, new Map()).get(x)).set(y, l);
  const via = id => id === to || hops.has(D.byId[id].type);
  const better = (p, q) => p.away - q.away || q.weight - p.weight || p.names.localeCompare(q.names);
  const seen = new Set([from]);
  let layer = new Map([[from, [{nodes: [from], links: [], away: 0, weight: 0, names: ''}]]]);
  while (layer.size && !layer.has(to)) {
    const next = new Map();
    for (const [x, paths] of layer) for (const [y, l] of adj.get(x) || []) {
      if (seen.has(y) || !via(y)) continue;
      const grown = paths.map(p => ({nodes: [...p.nodes, y], links: [...p.links, l], away: p.away + (y !== to && !isPerson(y)),
        weight: p.weight + l.weight, names: p.names + '|' + displayName(D.byId[y])}));
      next.set(y, [...(next.get(y) || []), ...grown].sort(better).slice(0, ROUTES));
    }
    for (const y of next.keys()) seen.add(y);
    layer = next;
  }
  return layer.get(to) || [];
}

function pathAt(pair) {
  const [a, b] = pair.split('~').map(id => D.byId[id] ? live(id) : '');
  const known = id => id && vis(D.byId[id]) ? id : '';
  const ends = {a: known(a), b: known(b)};
  const hidden = a && !ends.a || b && !ends.b;
  const state = !ends.a || !ends.b ? (hidden ? 'unknown' : 'pick') : ends.a === ends.b ? 'same' : null;
  const routes = state ? [] : connect(ends.a, ends.b, shownTypes('path'));
  const ids = [...new Set(routes.flatMap(r => r.nodes))];
  const {at, lanes} = chainLayout(routes);
  const keep = new Set(ids);
  const edges = drawnRows().filter(r => keep.has(r.source) && keep.has(r.target));
  const m = graphModel('path', ids, edges, at);
  const best = routes[0];
  const size = id => id === ends.a || id === ends.b ? CHAIN.end : best.nodes.includes(id) ? CHAIN.best : CHAIN.other;
  return {...m, ends, state: state || (routes.length ? 'found' : 'none'), routes, lanes,
    nodes: m.nodes.map(nd => nd.ghost ? nd : {...nd, focus: nd.id === ends.a || nd.id === ends.b, r: size(nd.id)}),
    path: {nodes: best?.nodes || [], keys: best?.links.map(l => l.key) || []}};
}

const CHAIN = {step: 220, gap: 96, lanes: [0, -1, 1], end: 10, best: 7, other: 6, bow: .18};

function chainLayout(routes) {
  const at = new Map();
  let lanes = 0;
  for (const r of routes) {
    if (r.nodes.every(id => at.has(id))) continue;
    r.nodes.forEach((id, k) => at.has(id) || at.set(id, [(k - (r.nodes.length - 1) / 2) * CHAIN.step, CHAIN.lanes[lanes] * CHAIN.gap]));
    lanes++;
  }
  return {at, lanes};
}

function wholeAt(picked) {
  const types = shownTypes('all');
  const keep = new Set(D.entities.filter(e => full(e) && types.has(e.type)).map(e => e.id));
  const focus = graphFocus(picked, () => storyRanked()[0]?.id ?? mainCharacter() ?? [...keep][0] ?? null);
  if (focus === null) return {view: 'all', focus, nodes: [], edges: [], links: [], ties: 0, cap: 0, bubbles: [], bands: []};
  keep.add(focus);
  const edges = drawnRows().filter(r => keep.has(r.source) && keep.has(r.target));
  const links = linksOf(edges), {partners, orgs} = ties();
  const degree = {};
  for (const r of edges) for (const id of [r.source, r.target]) degree[id] = (degree[id] || 0) + 1;
  const ids = [...keep].filter(id => degree[id] || G.isolates || id === focus);
  const lay = wholeLayout(focus, ids, links, orgs);
  const reach = id => partners.get(id) || 0;
  const main = new Set([focus, ...[...ids].sort((a, b) => reach(b) - reach(a) || byName(a, b)).slice(0, WHOLE.named)]);
  const nodes = ids.map(id => ({id, label: displayName(D.byId[id]), type: D.byId[id].type, degree: degree[id] || 0, focus: id === focus, named: main.has(id), ...fate(id), ...lay.at.get(id), r: id === focus ? WHOLE.centre : main.has(id) ? WHOLE.main : WHOLE.dot}));
  const cap = Math.max(WHOLE.minTies, ids.length);
  return withReveals({view: 'all', focus, nodes, edges, links: strongest(links, reach, cap), ties: links.length, cap, bubbles: [], bands: lay.bands}, besideRadially);
}

function strongest(links, reach, cap) {
  if (G.allTies) return links;
  const score = l => reach(l.a) + reach(l.b);
  const top = new Set([...links].sort((p, q) => q.weight - p.weight || score(q) - score(p) || cmp(p.key, q.key)).slice(0, cap));
  return links.filter(l => top.has(l) || l.fresh);
}

function hopsFrom(focus, links) {
  const near = new Map();
  for (const l of links) for (const [x, y] of [[l.a, l.b], [l.b, l.a]]) (near.get(x) || near.set(x, []).get(x)).push([y, l]);
  const hop = new Map([[focus, 0]]), via = new Map();
  for (let layer = [focus], h = 1; layer.length; h++) {
    const best = new Map();
    for (const x of layer) for (const [y, l] of near.get(x) || []) {
      if (hop.has(y)) continue;
      const seen = best.get(y);
      if (!seen || l.weight > seen.l.weight || l.weight === seen.l.weight && cmp(x, seen.x) < 0) best.set(y, {x, l});
    }
    for (const [y, {x, l}] of best) { hop.set(y, h); via.set(y, {from: x, link: l}); }
    layer = [...best.keys()];
  }
  return {hop, via};
}

function egoAt(focus) {
  const types = shownTypes('characters');
  const rows = drawnRows();
  const toFocus = new Map();
  for (const r of rows) {
    const other = r.source === focus ? r.target : r.target === focus ? r.source : null;
    if (other && types.has(D.byId[other].type)) (toFocus.get(other) || toFocus.set(other, []).get(other)).push(r);
  }
  const {partners, orgs} = ties();
  const score = new Map([...toFocus].map(([id, rs]) => [id, new Set(rs.flatMap(r => r.chapters)).size + Math.sqrt(partners.get(id) || 0)]));
  const ranked = [...score.keys()].sort((a, b) => score.get(b) - score.get(a) || byName(a, b));
  const groups = bubbleGroups(ranked.slice(G.limit), orgs, focus);
  const opened = new Set(groups.filter(g => G.open.has(g.key)).flatMap(g => g.members));
  const shown = ranked.filter((id, i) => i < G.limit || opened.has(id));
  const closed = groups.filter(g => !G.open.has(g.key));
  const ids = [focus, ...shown], keep = new Set(ids);
  const edges = rows.filter(r => keep.has(r.source) && keep.has(r.target));
  const lay = orbitLayout(focus, shown, closed, id => sectorFor(kindNow(toFocus.get(id))), orgs);
  const nodes = ids.map(id => ({id, label: displayName(D.byId[id]), type: D.byId[id].type, focus: id === focus, ...fate(id), ...lay.at.get(id)}));
  return withReveals({view: 'characters', focus, nodes, edges, links: linksOf(edges), bubbles: lay.bubbles, bands: lay.bands,
    more: Math.min(STEP, closed.reduce((s, g) => s + g.members.length, 0))}, besideRadially);
}

function besideRadially(nd) {
  const d = Math.hypot(nd.x, nd.y);
  return d ? {x: num(nd.x * (d + 44) / d), y: num(nd.y * (d + 44) / d)} : {x: 0, y: num(-ORBIT.R / 4)};
}

function withReveals(m, beside) {
  const drawn = new Set(m.nodes.map(nd => nd.id));
  const pairs = m.nodes.flatMap(nd => (D.parts[nd.id] || []).map(p => D.byId[p])
    .filter(p => p.merged.chapter === S.n && p.first < S.n && !drawn.has(p.id)).map(p => [p, nd]));
  const ghosts = pairs.map(([p, nd]) => ({id: p.id, label: displayName(p), type: p.type, focus: false, ghost: true, died: null, fresh: false, r: 6, ...beside(nd)}));
  const ties = pairs.map(([p, nd]) => ({key: p.id + '|' + nd.id, a: p.id, b: nd.id, rows: [], role: 'current', weight: 1, belief: false, fresh: false, same: S.n}));
  return {...m, nodes: [...m.nodes, ...ghosts], links: [...m.links, ...ties]};
}

function bubbleGroups(ids, orgs, focus) {
  const left = new Set(ids), groups = [];
  for (;;) {
    const count = new Map();
    for (const id of left) for (const o of orgs.get(id) || []) if (o !== focus) count.set(o, (count.get(o) || 0) + 1);
    const [org, n] = [...count].sort((a, b) => b[1] - a[1] || byName(a[0], b[0]))[0] || [];
    if (!org || n < 2) break;
    const members = [...left].filter(id => orgs.get(id)?.has(org));
    members.forEach(id => left.delete(id));
    groups.push({key: 'org:' + org, label: `+${n} ${displayName(D.byId[org])} members`, members});
  }
  const byType = new Map();
  for (const id of left) (byType.get(D.byId[id].type) || byType.set(D.byId[id].type, []).get(D.byId[id].type)).push(id);
  for (const [t, members] of byType) groups.push({key: 'type:' + t, label: `+${members.length} ${members.length === 1 ? t : plural(t)}`, members});
  return groups;
}

const LABEL_NUDGES = [0, 8, 16, 24, 32, 40, 48, 56, 64].flatMap(s => [0, 10, -10, 20, -20, 30, -30, 40, -40, 50, -50].map(t => [s, t])).sort((p, q) => Math.hypot(...p) - Math.hypot(...q));
const ORBIT = {R: 300, gap: 6, min: 24, rings: [.45, .7, .95], size: [12, 9, 6], centre: 20, stagger: .06, spacing: 40, compact: 24, inner: 10, growth: 8, lane: 85, most: .55};
const WHOLE = {minTies: 40, named: 24, first: 150, spacing: 34, lane: 34, gap: 26, centre: 9, main: 5.5, dot: 3, bands: 6};
const cmp = (x, y) => x < y ? -1 : x > y ? 1 : 0;
const rad = deg => deg * Math.PI / 180;

function orbitLayout(focus, shown, bubbles, sectorOf, orgs) {
  const sizes = ringSizes(shown.length), crowded = shown.length > ORBIT.compact;
  const tier = new Map(shown.map((id, i) => [id, ringOf(sizes, i)]));
  const faction = factionsOf(shown, orgs, focus);
  const order = (a, b) => !faction.get(a) - !faction.get(b) || cmp(faction.get(a), faction.get(b)) || D.byId[a].first - D.byId[b].first || cmp(a, b);
  const mainSector = g => {
    const n = {};
    for (const id of g.members) n[sectorOf(id)] = (n[sectorOf(id)] || 0) + 1;
    return SECTORS.map(s => s.key).sort((x, y) => (n[y] || 0) - (n[x] || 0))[0];
  };
  const sectors = SECTORS.map(({key}) => ({key, ids: shown.filter(id => sectorOf(id) === key).sort(order), bubbles: bubbles.filter(g => mainSector(g) === key)}));
  const slots = s => s.ids.length + s.bubbles.length;
  spreadSectors(sectors, slots);
  const used = sectors.filter(slots);
  const R = crowded ? ORBIT.R : Math.max(ORBIT.R, ...used.map(s => slots(s) * ORBIT.spacing / (ORBIT.rings[0] * rad(s.w))));
  const lastRing = sizes.length - 1;
  const slotsOf = s => [...s.ids.map(id => ({id, ring: tier.get(id)})), ...s.bubbles.map(g => ({g, ring: lastRing}))];
  const grids = s => crowded ? sizes.map((_, t) => slotsOf(s).filter(x => x.ring === t)) : [slotsOf(s)];
  const radii = crowded ? ringRadii(sizes.map((_, t) => Math.max(0, ...used.map(s => grids(s)[t].length * ORBIT.spacing / rad(s.w))))) : ORBIT.rings.map(ring => R * ring);
  const size = t => ORBIT.size[Math.min(t, ORBIT.size.length - 1)];
  const at = new Map([[focus, {x: 0, y: 0, r: ORBIT.centre}]]), placed = [], runs = [];
  for (const s of sectors) {
    const mid = num(rad(s.a + s.w / 2));
    for (const grid of grids(s)) grid.forEach((slot, i) => {
      const t = rad(s.a + s.w * (i + .5) / grid.length), wiggle = grid.length > 1 ? (i % 2 ? 1 : -1) * ORBIT.stagger * R : 0;
      const r = (slot.g ? radii[lastRing] + 2 * ORBIT.stagger * R : radii[slot.ring]) + wiggle;
      const point = {x: num(r * Math.cos(t)), y: num(r * Math.sin(t)), mid};
      if (slot.g) placed.push({...slot.g, ...point, r: num(Math.min(24, 11 + 2 * Math.sqrt(slot.g.members.length)))});
      else at.set(slot.id, {...point, r: size(slot.ring)});
    });
    sizes.forEach((_, t) => {
      for (const id of s.ids.filter(x => tier.get(x) === t && faction.get(x))) {
        const run = runs.at(-1);
        if (run?.org === faction.get(id) && run.sector === s.key && run.ring === t) run.members.push(id);
        else runs.push({org: faction.get(id), sector: s.key, ring: t, members: [id]});
      }
    });
  }
  return {at, bubbles: placed, bands: namedBands(runs.map(b => ({...b, r: size(b.ring)})))};
}

function ringSizes(n) {
  if (n <= ORBIT.compact) return ORBIT.rings.map((_, t) => Math.ceil(n * (t + 1) / 3) - Math.ceil(n * t / 3));
  const caps = [ORBIT.inner];
  while (caps.reduce((sum, c) => sum + c) < n) caps.push(caps.at(-1) + ORBIT.growth);
  const room = caps.reduce((sum, c) => sum + c), sizes = caps.map(c => Math.floor(c * n / room));
  sizes[sizes.length - 1] += n - sizes.reduce((sum, c) => sum + c);
  return sizes;
}

function ringOf(sizes, i) {
  let t = 0;
  for (let left = i; left >= sizes[t]; left -= sizes[t++]);
  return t;
}

function ringRadii(needs) {
  const radii = [];
  needs.forEach((need, t) => radii.push(num(Math.max(need, t ? radii[t - 1] + ORBIT.lane : ORBIT.R * ORBIT.rings[0]))));
  return radii;
}

function factionsOf(ids, orgs, focus) {
  const members = new Map();
  for (const id of ids) for (const o of orgs.get(id) || []) if (o !== focus) members.set(o, (members.get(o) || 0) + 1);
  return new Map(ids.map(id => [id, [...(orgs.get(id) || [])].filter(o => members.get(o) >= 2).sort((a, b) => members.get(b) - members.get(a) || byName(a, b))[0] || '']));
}

function spreadSectors(sectors, slots) {
  const used = sectors.filter(slots), total = used.reduce((n, s) => n + slots(s), 0);
  const spare = 360 - sectors.length * ORBIT.gap - used.length * ORBIT.min;
  for (const s of sectors) s.w = slots(s) ? ORBIT.min + spare * slots(s) / total : 0;
  let a = -90 - sectors[0].w / 2;
  for (const s of sectors) { s.a = a; a += s.w + ORBIT.gap; }
}

function namedBands(runs) {
  const tints = [...new Set(runs.map(b => b.org))];
  return runs.map(b => ({...b, name: displayName(D.byId[b.org]), tint: tints.indexOf(b.org) % 6 + 1}));
}

function wholeLayout(focus, ids, links, orgs) {
  const {hop, via} = hopsFrom(focus, links);
  const others = ids.filter(id => id !== focus), reached = others.filter(id => hop.has(id));
  const sectorOf = new Map();
  for (const id of [...reached].sort((a, b) => hop.get(a) - hop.get(b))) sectorOf.set(id, hop.get(id) === 1 ? sectorFor(via.get(id).link.group) : sectorOf.get(via.get(id).from));
  const faction = factionsOf(others, orgs, focus);
  const kind = id => TYPE_GROUPS.findIndex(g => groupTypes(g).includes(D.byId[id].type));
  const at = new Map([[focus, {x: 0, y: 0}]]), sway = new Map(), runs = [];
  const order = (a, b) => kind(a) - kind(b) || !faction.get(a) - !faction.get(b) || cmp(faction.get(a), faction.get(b)) || (sway.get(via.get(a)?.from) || 0) - (sway.get(via.get(b)?.from) || 0) || D.byId[a].first - D.byId[b].first || cmp(a, b);
  const sectors = SECTORS.map(({key}) => ({key, n: reached.filter(id => sectorOf.get(id) === key).length}));
  spreadSectors(sectors, s => s.n);
  let radius = WHOLE.first;
  const ring = (arcs, h) => {
    const lanes = Math.max(1, ...arcs.map(({s, ids: arc}) => Math.ceil(arc.length * WHOLE.spacing / (radius * rad(s.w)))));
    for (const {s, ids: arc} of arcs) {
      arc.sort(order).forEach((id, i) => {
        const t = rad(s.a + s.w * (i + .5) / arc.length), r = radius + WHOLE.lane * (i % lanes);
        sway.set(id, (i + .5) / arc.length);
        at.set(id, {x: num(r * Math.cos(t)), y: num(r * Math.sin(t)), mid: num(rad(s.a + s.w / 2))});
        const run = runs.at(-1);
        if (!faction.get(id)) return;
        if (run?.org === faction.get(id) && run.sector === s.key && run.ring === h) run.members.push(id);
        else runs.push({org: faction.get(id), sector: s.key, ring: h, r: WHOLE.dot, members: [id]});
      });
    }
    radius += lanes * WHOLE.lane + WHOLE.gap;
  };
  for (const h of [...new Set(reached.map(id => hop.get(id)))].sort((a, b) => a - b))
    ring(sectors.map(s => ({s, ids: reached.filter(id => hop.get(id) === h && sectorOf.get(id) === s.key)})).filter(({ids: arc}) => arc.length), h);
  const stray = others.filter(id => !hop.has(id));
  if (stray.length) ring([{s: {key: 'none', a: -90, w: 360}, ids: stray}], Infinity);
  const bands = namedBands(runs);
  const biggest = new Set([...bands].filter(b => b.members.length >= 3).sort((a, b) => b.members.length - a.members.length || cmp(a.name, b.name)).slice(0, WHOLE.bands));
  return {at, bands: bands.map(b => ({...b, shout: biggest.has(b)}))};
}

function graphModel(view, ids, edges, at) {
  const {partners} = ties();
  const degree = {};
  for (const r of edges) for (const id of [r.source, r.target]) degree[id] = (degree[id] || 0) + 1;
  const nodes = ids.map(id => {
    const e = D.byId[id], [x, y] = at.get(id);
    return {id, label: displayName(e), type: e.type, degree: degree[id] || 0, focus: false, ...fate(id), x: num(x), y: num(y), r: num(Math.min(18, 6 + 1.5 * Math.sqrt(partners.get(id) || 0)))};
  });
  return withReveals({view, focus: null, nodes, edges, links: linksOf(edges), bubbles: []}, nd => ({x: num(nd.x + 46), y: num(nd.y - 46)}));
}

function linksOf(edges) {
  const by = new Map();
  for (const r of edges) {
    const [a, b] = r.source < r.target ? [r.source, r.target] : [r.target, r.source];
    const key = a + '|' + b;
    const l = by.get(key) || by.set(key, {key, a, b, rows: [], chapters: new Set()}).get(key);
    l.rows.push(r);
    r.chapters.forEach(c => l.chapters.add(c));
  }
  const roleOf = rows => ['current', 'aside', 'erased'].find(rl => rows.some(r => r.role === rl));
  return [...by.values()].map(({chapters, ...l}) =>
    ({...l, role: roleOf(l.rows), group: kindNow(l.rows), weight: chapters.size, belief: l.rows.every(r => r.status === 'belief'), fresh: Math.min(...chapters) === S.n}));
}

const typeColor = t => { const i = D.typeOrder.indexOf(t); return i < 8 ? `var(--g${i + 1})` : 'var(--muted)'; };
const num = x => Math.round(x * 10) / 10;

const curve = ([x1, y1], [x2, y2], k) => `M${num(x1)} ${num(y1)}Q${num((x1 + x2) / 2 - (y2 - y1) * k)} ${num((y1 + y2) / 2 + (x2 - x1) * k)} ${num(x2)} ${num(y2)}`;

const clip = (t, n) => t.length > n ? t.slice(0, n - 1) + '…' : t;
const relText = r => `${displayName(D.byId[r.source])} ${predicate(r.label)}${r.badge ? ` (${r.badge})` : ''} ${displayName(D.byId[r.target])}${r.detail ? ' ' + r.detail : ''}${suspicion(r) ? ` (${suspicion(r)})` : ''}, ch ${r.chapters.join(', ')}`;

const placeAt = (x, y) => `data-x="${x}" data-y="${y}" transform="translate(${x} ${y})"`;
const DAGGER = '†';
const labelSvg = (id, text, x, y, [ox, oy, anchor], big, {died, ghost, quiet} = {}) =>
  `<text class="lbl${big ? ' big' : ''}${quiet ? ' minor hide' : ''}${died != null ? ' dead' : ''}${ghost ? ' ghost' : ''}" data-for="${esc(id)}" data-ox="${ox}" data-oy="${oy}" x="${num(x + ox)}" y="${num(y + oy)}"${anchor ? ` style="text-anchor:${anchor}"` : ''}>${esc(text)}${died != null ? `<tspan class="dagger"> ${DAGGER}</tspan>` : ''}</text>`;
const nodeCls = nd => `gnode${nd.focus ? ' focus' : ''}${nd.died != null ? ' dead' : ''}${nd.fresh ? ' new' : ''}${nd.ghost ? ' ghost' : ''}`;
const nodeSays = nd => `${nd.died != null ? `, died ch ${nd.died}` : ''}${nd.fresh ? ', new this chapter' : ''}${nd.ghost ? `, revealed ch ${S.n} to be ${displayName(D.byId[live(nd.id)])}` : ''}`;
const nodeMarks = nd => `${nd.fresh ? `<circle class="ring" r="${num(nd.r + 4)}"/>` : ''}${nd.died != null ? `<title>${esc(nd.label)} died ch ${nd.died}</title>` : ''}`;
const svgFrame = (cls, label, {bands, links, nodes, labels}) =>
  `<svg class="graph${cls}" id="graph" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="${esc(label)}"><g id="graph-view"><g class="bands">${bands.join('')}</g><g class="edges">${links.join('')}</g><g class="nodes">${nodes.join('')}</g><g class="labels">${labels.join('')}</g></g></svg>`;
const edgeTitle = l => {
  if (l.same) return `Same person, revealed ch ${l.same}`;
  const history = tieHistory(l.rows);
  return esc(l.rows.map(relText).join('; ')) + (history ? '&#10;' + esc(history) : '');
};
const edgeSvg = (l, cls, k, d, style) =>
  `<path class="edge ${l.role}${l.belief ? ' belief' : ''}${l.fresh ? ' new' : ''}${l.same ? ' same' : ''}${cls}" data-a="${l.a}" data-b="${l.b}" data-k="${k}" d="${d}" style="stroke:var(${l.same ? '--muted' : '--r-' + l.group})${style}"><title>${edgeTitle(l)}</title></path>`;

const hitRing = (x, y, spots) => `<circle class="hit" r="22" style="--near:${num(Math.min(...spots.map(([px, py]) => Math.hypot(px - x, py - y) || Infinity)) / 2)}px"/>`;
const dotSvg = (nd, spots, cls, says) =>
  `<g class="${nodeCls(nd)}${cls}" data-gn="${nd.id}" data-r="${nd.r}" ${placeAt(nd.x, nd.y)} style="--r:${nd.r}" tabindex="0" role="button" aria-label="${esc(nd.label)}, ${esc(nd.type)}${says}${nodeSays(nd)}">${hitRing(nd.x, nd.y, spots)}${nodeMarks(nd)}<circle r="${nd.r}"/></g>`;

function chainSvg(m) {
  const pos = new Map(m.nodes.map(nd => [nd.id, [nd.x, nd.y]]));
  const spots = [...pos.values()];
  const first = new Set(m.path.keys), onRoute = new Set(m.routes.flatMap(r => r.links.map(l => l.key))), bestNodes = new Set(m.path.nodes);
  const links = m.links.map(l => {
    const k = l.same || onRoute.has(l.key) ? 0 : CHAIN.bow;
    return edgeSvg(l, first.has(l.key) ? ' path' : onRoute.has(l.key) ? ' route' : '', k, curve(pos.get(l.a), pos.get(l.b), k), '');
  });
  const nodes = m.nodes.map(nd => dotSvg(nd, spots, bestNodes.has(nd.id) ? ' path' : '', nd.focus ? ', end of the chain' : ''));
  const labels = m.nodes.map(nd => labelSvg(nd.id, nd.label, nd.x, nd.y, [0, num(nd.r + 12), 'middle'], nd.focus, nd));
  return svgFrame(` orbit haspath lanes${m.lanes}`, `Shortest chains between ${displayName(D.byId[m.ends.a])} and ${displayName(D.byId[m.ends.b])} by chapter ${S.n}`, {bands: [], links, nodes, labels});
}

function bowK([x1, y1], [x2, y2], [tx, ty], size) {
  const px = y1 - y2, py = x2 - x1;
  return num(Math.sign(px * (tx - (x1 + x2) / 2) + py * (ty - (y1 + y2) / 2) || 1) * size);
}

function outward({x, y, r}, big) {
  if (big) return [0, r + 12, 'middle'];
  const t = Math.atan2(y, x), c = Math.cos(t), s = Math.sin(t), d = r + 6;
  return [num(d * c), num(d * s + (Math.abs(c) < .3 ? Math.sign(s) * 6 : 0)), c > .3 ? 'start' : c < -.3 ? 'end' : 'middle'];
}

function bandPath(centres, r) {
  const angles = centres.map(([x, y]) => Math.atan2(y, x)), radii = centres.map(p => Math.hypot(...p));
  const ts = angles.map(t => angles[0] + Math.atan2(Math.sin(t - angles[0]), Math.cos(t - angles[0])));
  const mean = radii.reduce((s, x) => s + x, 0) / radii.length, t0 = Math.min(...ts), t1 = Math.max(...ts);
  const p = t => `${num(mean * Math.cos(t))} ${num(mean * Math.sin(t))}`;
  const width = num(Math.max(...radii) - Math.min(...radii) + 2 * r + 10), out = mean + width / 2 + 8, mid = (t0 + t1) / 2;
  return [`M${p(t0)}A${num(mean)} ${num(mean)} 0 ${t1 - t0 > Math.PI ? 1 : 0} 1 ${p(t1)}`, width, [num(out * Math.cos(mid)), num(out * Math.sin(mid))]];
}

function orbitSvg(m) {
  const whole = m.view === 'all';
  const pos = new Map([...m.nodes.map(nd => [nd.id, [nd.x, nd.y]]), ...m.bubbles.map(b => [b.key, [b.x, b.y]])]);
  const byId = new Map(m.nodes.map(nd => [nd.id, nd]));
  const spots = [...pos.values()];
  const links = m.links.map(l => {
    const p = pos.get(l.a), q = pos.get(l.b), other = byId.get(l.a === m.focus ? l.b : l.b === m.focus ? l.a : null);
    const reach = other && Math.hypot(other.x, other.y), turn = other && Math.abs(Math.sin(other.mid - Math.atan2(other.y, other.x)));
    const k = l.same ? 0 : other ? bowK(p, q, [reach * Math.cos(other.mid), reach * Math.sin(other.mid)], Math.min(.2, turn * .8)) : bowK(p, q, [0, 0], .15);
    return edgeSvg(l, '', k, curve(p, q, k), '');
  });
  const bands = m.bands.map(b => {
    const [d, width, [x, y]] = bandPath(b.members.map(id => pos.get(id)), b.r);
    return `<g class="band" data-members="${b.members.join(' ')}" data-r="${b.r}" style="--h:var(--h${b.tint})"><path d="${d}" stroke-width="${width}"/><title>${esc(b.name)}</title>${b.shout ? `<text x="${x}" y="${y}">${esc(b.name)}</text>` : ''}</g>`;
  });
  const nodes = m.nodes.map(nd => dotSvg(nd, spots, '', nd.focus ? ', centre' : ''));
  const bubbles = m.bubbles.map(b =>
    `<g class="gbubble" data-gb="${esc(b.key)}" data-r="${b.r}" ${placeAt(b.x, b.y)} tabindex="0" role="button" aria-label="${esc(b.label)}, show them">${hitRing(b.x, b.y, spots)}<circle r="${b.r}"/><text class="ini" font-size="${num(b.r * 0.62)}">+${b.members.length}</text></g>`);
  const labels = [...m.nodes.map(nd => labelSvg(nd.id, nd.label, nd.x, nd.y, outward(nd, nd.focus), nd.focus, {...nd, quiet: whole && !nd.named && !nd.ghost})),
    ...m.bubbles.map(b => labelSvg(b.key, b.label.replace(/^\+\d+ /, ''), b.x, b.y, outward(b, false), false))];
  const says = whole ? `Every entry shown, in rings of steps from ${displayName(D.byId[m.focus])}, by chapter ${S.n}` : `Characters linked to ${displayName(D.byId[m.focus])} by chapter ${S.n}`;
  return svgFrame(whole ? ' orbit whole' : ' orbit', says, {bands, links, nodes: [...nodes, ...bubbles], labels});
}

const centreRoute = id => (G.model?.view === 'all' ? 'graph:all:' : 'graph:') + id;

function graphCard(id) {
  const m = G.model, e = D.byId[id];
  if (!e) return '<p class="muted">Hover or tab to an entry to see who it is.</p>';
  const l = lede(e);
  const rels = m.focus && id !== m.focus ? m.edges.filter(r => [r.source, r.target].includes(id) && [r.source, r.target].includes(m.focus)) : [];
  const centre = id === m.focus ? '' : `<a data-gc="${id}" href="#${hashFor({p: centreRoute(id)})}">Centre here</a>`;
  const {died, fresh} = fate(id);
  const known = (D.parts[id] || []).map(p => D.byId[p]).filter(p => p.merged.chapter <= S.n && p.first < p.merged.chapter);
  const aka = known.map(p => `Also known as ${esc(displayName(p))} since ch ${p.merged.chapter}`);
  if (live(id) !== id) aka.push(`Revealed ch ${e.merged.chapter} to be ${esc(displayName(D.byId[live(id)]))}`);
  return `<div class="gct">${esc(cap(e.type))}${id === m.focus ? ' &middot; centre' : ''} &middot; ${fresh ? 'new this chapter' : `since ch ${e.first}`}${died != null ? ` &middot; died ch ${died}` : ''}</div><b class="gcn">${esc(displayName(e))}</b>`
    + (aka.length ? `<p class="gaka">${aka.join('<br>')}</p>` : '')
    + (l.text ? `<p>${esc(clip(l.text, 200))}</p>` : '')
    + (rels.length ? `<ul>${rels.slice(0, 4).map(r => `<li>${esc(relText(r))}</li>`).join('')}</ul>` : '')
    + `<div class="gca"><a data-gopen="${id}" href="#${hashFor({p: 'e:' + id, tab: ''})}">Open page</a>${centre}</div>`;
}

function graphTabs(view) {
  const whole = view === 'all';
  const tabs = Object.entries(GRAPH_VIEWS).filter(([, v]) => v.tab && (!v.when || v.when())).map(([k, v]) => `<a ${goTo(v.route)} class="${view === k ? 'on' : ''}">${v.label}</a>`).join('');
  return `<div class="tabs gtabs" role="tablist">${tabs}<a ${goTo(whole ? GRAPH_VIEWS.characters.route : GRAPH_VIEWS.all.route)} class="gwhole${whole ? ' on' : ''}" role="switch" aria-checked="${whole}">Whole book</a></div>`;
}

function freshNote(parts) {
  const shown = Object.entries(parts).filter(([, n]) => n);
  const total = shown.reduce((s, [, n]) => s + n, 0);
  return total ? `<p class="gnew"><span class="newtag">new</span> ${total} new this chapter: ${shown.map(([noun, n]) => count(n, noun)).join(', ')}</p>` : '';
}

const FULL_ICON = {enter: 'M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4', leave: 'M6 2v4H2M10 2v4h4M14 10h-4v4M2 10h4v4'};
const NETWORK_VIEWS = new Set(['characters', 'path', 'all']);

function setFull(on) {
  G.full = on;
  document.body.classList.toggle('gfull', on);
  G.view = null;
  if (on) document.documentElement.requestFullscreen?.()?.catch(() => {});
  else if (document.fullscreenElement) document.exitFullscreen();
}

function toggleFull(on) {
  setFull(on);
  render();
  $('gfull')?.focus();
}

function renderGraph(arg) {
  const m = G.model = graphAt(arg);
  if (m.view === 'story') return renderStory(m);
  if (m.view === 'matrix') return renderMatrix(m);
  if (m.view === 'factions') return renderFactions(m);
  if (m.view === 'ladder') return renderLadder(m);
  if (m.view === 'family') return renderFamily(m);
  if (m.view === 'places') return renderPlaces(m);
  if (m.view === 'masks') return renderMasks(m);
  if (arg && arg !== 'all' && m.focus) store.set('graph-focus', m.focus);
  const types = shownTypes(m.view);
  const c = counts();
  const visTypes = Object.entries(c).sort((a, b) => D.typeOrder.indexOf(a[0]) - D.typeOrder.indexOf(b[0]));
  const famCount = {};
  for (const r of edgesAt()) if (G.erased || r.role !== 'erased') famCount[r.family] = (famCount[r.family] || 0) + 1;
  const erasedN = edgesAt().filter(r => r.role === 'erased').length;
  const typeChips = visTypes.map(([t, c]) => `<a data-gt="${esc(t)}" class="${types.has(t) ? 'on' : ''}" role="switch" aria-checked="${types.has(t)}"><i class="dot" style="background:${typeColor(t)}"></i>${esc(catName(t))} ${c}</a>`).join('');
  const whole = m.view === 'all', path = m.view === 'path';
  const bar = graphTabs(m.view) + freshNote({entry: m.nodes.filter(nd => nd.fresh).length, tie: m.links.filter(l => l.fresh).length});
  const entries = m.nodes.filter(nd => !nd.ghost).length;
  const subtitle = path ? pathSummary(m) : whole ? wholeSummary(m, entries)
    : `${entries - 1} of ${entries - 1 + m.bubbles.reduce((s, b) => s + b.members.length, 0)} linked to ${entLink(m.focus)} by chapter ${S.n}${backToDefault(m.focus)}`;
  const option = (key, text) => `<label class="gopt"><input type="checkbox" data-gopt="${key}"${G[key] ? ' checked' : ''}> ${text}</label>`;
  const toggles = (whole ? option('isolates', 'Entries with no relations') + (m.ties > m.cap ? option('allTies', 'Show all ties') : '') : '')
    + (erasedN ? `<label class="gopt"><input type="checkbox" data-gopt="erased"${G.erased ? ' checked' : ''}> Erased timelines (${erasedN})</label>` : '');
  const more = m.more ? `<div class="gmorebtns"><button class="gmorebtn" data-gmore>Show ${m.more} more</button><button class="gmorebtn" data-gall>Show all</button></div>` : '';
  const routes = path ? tieStory(m) + routeList(m) : '';
  const empty = path ? '' : '<p class="muted gempty">No relations to draw with these filters at this chapter.</p>';
  const zooms = m.nodes.length ? '<button class="iconbtn" data-gz="1.3" aria-label="Zoom in">+</button><button class="iconbtn" data-gz="0.77" aria-label="Zoom out">&minus;</button><button class="iconbtn" data-gz="fit" aria-label="Fit to screen">&#9635;</button>' : '';
  const fullLabel = G.full ? 'Leave full screen' : 'Full screen';
  const card = `<div class="gcard" id="gcard" aria-live="polite">${graphCard(m.focus)}</div>`;
  const body = m.nodes.length || G.full ? `<div class="graphwrap">${m.nodes.length ? (path ? chainSvg : orbitSvg)(m) : empty}<div class="gzoom">${zooms}<button class="iconbtn" id="gfull" data-gfull aria-pressed="${!!G.full}" aria-label="${fullLabel}" title="${fullLabel}"><svg class="ficon" viewBox="0 0 16 16" aria-hidden="true"><path d="${G.full ? FULL_ICON.leave : FULL_ICON.enter}"/></svg></button></div>${m.nodes.length && path ? card : ''}${more}</div>` : empty;
  const finder = path ? pathPicker(m) : `<div class="searchwrap"><input id="gq" type="search" placeholder="Centre on an entry" autocomplete="off" aria-label="Centre on an entry"><div class="results" id="gqres" role="listbox"></div></div>`;
  return `<div class="crumbs"><a ${goTo('home')}>Home</a></div><h1>Graph</h1>${bar}${path ? `<p class="pathsum" aria-live="polite">${subtitle}</p>` : `<div class="subtitle">${subtitle}</div>`}
  <div class="gstage${m.nodes.length || G.full ? ' drawn' : ''}"><aside class="gpanel" aria-label="Legend and filters"><div class="gfilters"><div class="gctl">${finder}${toggles}</div>
  ${groupedControls(types, famCount, c)}<details class="gmoref"${G.moreOpen ? ' open' : ''}><summary>More filters</summary><div class="pills gchips">${typeChips}</div></details></div>
  ${!path && m.nodes.length ? card : ''}<p class="muted glegend">${path ? 'The first chain is drawn bold. Show limits which kinds of entry a chain may pass through. ' : whole ? 'Each ring is one more step from the centre, and each slice follows the kind of tie that leads there. Entries with no path to the centre sit in the outer band. Names beyond the main entries appear as you zoom in or hover. Select an entry to centre the graph on it. ' : 'Family and romance sit at the top, then allies, service, and teaching, then hostility and investigation, then membership and faith, and things and places clockwise. The strongest ties sit nearest the centre, and a faint band joins members of one group. Select an entry to centre the graph on it, or tap it once on a touch screen to preview it; double-click, press O, or use Open page to read its page. '}Each line colour is one kind of tie, named under Lines; hover a name there for what it covers, or hover a line for the exact relations. Dashed lines are suspicions, dotted lines flashbacks.${m.links.some(l => l.same) ? ' A grey dashed line joins a name to the person it is revealed to be in this chapter.' : ''} Drag to pan, pinch or scroll to zoom.</p></aside><div class="gdraw">${body}</div></div>${routes}`;
}

function backToDefault(focus) {
  const home = mainCharacter();
  return home && home !== focus ? ` <a class="gback" data-gback ${goTo(GRAPH_VIEWS.characters.route)}>&times; Back to ${esc(displayName(D.byId[home]))}</a>` : '';
}

function wholeSummary(m, entries) {
  const drawn = m.links.filter(l => !l.same).length, noun = shownTypes('all').size === 1 && shownTypes('all').has('character') ? 'people' : 'entries';
  const shown = drawn < m.ties ? `the ${drawn} longest-running of ${m.ties} ties` : `all ${m.ties} ties`;
  return `${entries} ${noun} around ${entLink(m.focus)}, ${shown}, by chapter ${S.n}`;
}

function pathPicker(m) {
  const box = (id, end, label) => `<div class="searchwrap"><input id="${id}" type="search" placeholder="${label}" autocomplete="off" aria-label="${label}" value="${end ? esc(displayName(D.byId[end])) : ''}"><div class="results" id="${id}res" role="listbox"></div></div>`;
  const {a, b} = m.ends;
  const swap = a && b ? `<a class="pathswap" ${goTo(pairRoute(b, a))} aria-label="Swap the two entries">&#8644;</a>` : '';
  return `<div class="pathpick">${box('pa', a, 'From an entry')}${swap}${box('pb', b, 'To another entry')}</div>`;
}

function pathSummary(m) {
  const {a, b} = m.ends;
  if (m.state === 'unknown') return `One of these entries is not introduced by chapter ${S.n}. Move the slider forward or pick another entry.`;
  if (m.state === 'pick') return a || b ? `Pick a second entry to see how ${entLink(a || b)} is connected to it by chapter ${S.n}.` : `Pick two entries to see the shortest chain of relations between them, using only what is known by chapter ${S.n}.`;
  if (m.state === 'same') return `Both names lead to ${entLink(a)} by chapter ${S.n}.`;
  if (m.state === 'none') {
    const narrowed = shownTypes('path').size < D.typeOrder.length ? ' through the kinds of entry shown' : '';
    return `${entLink(a)} and ${entLink(b)} are not connected yet${narrowed} by chapter ${S.n}.`;
  }
  const steps = m.routes[0].links.length;
  const link = `<a ${goTo(pairRoute(a, b))} class="muted">Link to this</a>`;
  return `${entLink(a)} and ${entLink(b)} are ${steps === 1 ? 'directly connected' : `${steps} steps apart`} by chapter ${S.n}. ${link}`;
}

function hopRow(l) {
  const r = leadRow(l.rows, l.group);
  const sentence = row => `${entLink(row.source)} <span class="crole">${esc(predicate(row.label))}</span> ${entLink(row.target)}${detailHtml(row, Math.max(...row.chapters))}${row.badge ? ` <span class="badge">${esc(row.badge)}</span>` : ''}${beliefBadge(row)}`;
  const said = [...new Set(l.rows.flatMap(row => row.quotes || []))];
  const others = l.rows.filter(row => row !== r);
  const body = said.length || others.length ? l.rows.map(row => `<div class="qmeta">${sentence(row)} ${row.chapters.slice().sort((p, q) => p - q).map(chLink).join(' ')}</div>${quotes(row.quotes)}`).join('') : '';
  const noun = said.length ? quoteNoun(said) : `all ${l.rows.length} ties`;
  const since = Math.min(...l.rows.flatMap(row => row.chapters));
  return `<li class="hop">${swatch(l.group)}${expandRow(`${sentence(r)}${others.length ? ` <small>+${others.length}</small>` : ''} <span class="csince">since ${chLink(since)}</span>`, noun, body)}</li>`;
}

function pairLog(a, b) {
  const between = r => [live(r.source), live(r.target)].sort().join('~') === [a, b].sort().join('~');
  return until(D.relations).filter(r => between(r) && role(r.timeline) !== 'erased').sort((x, y) => x.chapter - y.chapter);
}

function tieStory(m) {
  const log = m.ends.a && m.ends.b ? pairLog(m.ends.a, m.ends.b) : [];
  if (!log.length) return '';
  const row = r => `<li class="hop">${swatch(groupOf(r.family || 'other'))}${chLink(r.chapter)} ${entLink(live(r.source))} <span class="crole">${esc(predicate(r.type))}</span> ${entLink(live(r.target))}${r.status === 'belief' ? ' <span class="badge belief">belief</span>' : ''}${quotes(r.unverified ? [] : r.quotes)}</li>`;
  return `<section class="route best"><div class="routehead">How this tie changed &middot; ${log.length} moments</div><ol class="hops">${log.map(row).join('')}</ol></section>`;
}

function routeList(m) {
  if (m.state !== 'found') return '';
  const routes = pairLog(m.ends.a, m.ends.b).length ? m.routes.filter(r => r.links.length > 1) : m.routes;
  return `<ol class="routes">${routes.map((r, i) => {
    const through = r.nodes.slice(1, -1).map(id => displayName(D.byId[id]));
    const head = `<div class="routehead">${routes.length > 1 ? `Chain ${i + 1}` : 'Chain'}${through.length ? ` &middot; through ${esc(through.join(', '))}` : ''}</div>`;
    return `<li class="route${i ? '' : ' best'}">${head}<ol class="hops">${r.links.map(hopRow).join('')}</ol></li>`;
  }).join('')}</ol>`;
}

function groupedControls(types, famCount, c) {
  const state = (members, on) => members.every(on) ? 'on' : members.some(on) ? 'on part' : '';
  const ents = TYPE_GROUPS.map(g => [g, groupTypes(g)]).filter(([, ts]) => ts.some(t => c[t])).map(([g, ts]) => {
    const cls = state(ts, t => types.has(t));
    return `<a data-ggt="${g.key}" class="${cls}" role="switch" aria-checked="${cls === 'on'}"><span>${g.label}</span><small>${ts.reduce((s, t) => s + (c[t] || 0), 0)}</small></a>`;
  }).join('');
  const rels = REL_GROUPS.filter(g => g.fams.some(f => famCount[f])).map(g => {
    const cls = state(g.fams, f => !G.hideFams.has(f));
    return `<a data-ggr="${g.key}" class="${cls}" role="switch" aria-checked="${cls === 'on'}" title="${esc(cap(g.says))}">${swatch(g.key)}${esc(g.label)}<small>${famCount[g.key]}</small></a>`;
  }).join('');
  return `<div class="gquiet"><span class="gq-lab">Show</span>${ents}<span class="gq-sep"></span><span class="gq-lab">Lines</span>${rels}</div>`;
}

function toggleGroup(members, isOn, setOn) {
  const on = !members.every(isOn);
  members.forEach(m => setOn(m, on));
  render();
}

const CONN = {rows: 6, marks: 5};

function tieMarks(rows) {
  const marks = [];
  for (const c of [...new Set(rows.flatMap(r => r.chapters))].sort((a, b) => a - b)) {
    const group = kindNow(rows.map(r => ({...r, chapters: r.chapters.filter(x => x <= c)})).filter(r => r.chapters.length));
    if (group !== marks.at(-1)?.group) marks.push({chapter: c, group});
  }
  return marks;
}
const fewMarks = marks => marks.length > CONN.marks ? [marks[0], ...marks.slice(1 - CONN.marks)] : marks;

function leadRow(rows, group) {
  const latest = r => Math.max(...r.chapters);
  const own = rows.filter(r => groupOf(r.family) === group);
  return (own.length ? own : rows).reduce((a, b) => latest(b) >= latest(a) ? b : a);
}

function connRow(id, other, rows) {
  const name = displayName(D.byId[id]), me = esc(name);
  const group = pairGroup(rows);
  const r = leadRow(rows, group);
  const holder = r.status !== 'belief' ? '' : holderName(r.by) === name ? 'suspected' : suspicion(r) || 'suspected';
  const end = x => x === other ? entLink(other) : me;
  const kinds = new Set(rows.map(x => wordKey(wording(x)))).size;
  const since = Math.min(...rows.flatMap(x => x.chapters));
  const pct = c => num(100 * c / S.n);
  const marks = tieMarks(rows);
  const ticks = fewMarks(marks).map(m => `<i data-ch="${m.chapter}" style="left:${pct(m.chapter)}%;--c:var(--r-${m.group})"></i>`).join('');
  const segments = marks.map((m, i) => `<b${holder ? ' class="belief"' : ''} style="left:${pct(m.chapter)}%;right:${num(100 - pct(marks[i + 1]?.chapter ?? S.n))}%;--c:var(--r-${m.group})"></b>`).join('');
  const story = marks.map((m, i) => `${i ? 'then ' + REL_GROUPS.find(g => g.key === m.group).label.toLowerCase() : 'from'} ch ${m.chapter}`).join(', ');
  return `<li><span class="cwho" title="${rows.map(x => esc(relText(x))).join('&#10;')}">${end(r.source)} <span class="crole">${esc(predicate(r.label))}</span> ${end(r.target)}${detailHtml(r, Math.max(...r.chapters))}${r.badge ? ` <span class="badge">${esc(r.badge)}</span>` : ''}`
    + `${holder ? ` <i class="sus">${esc(holder)}</i>` : ''}${kinds > 1 ? ` <small>+${kinds - 1}</small>` : ''}</span>`
    + ` <a class="csince" ${goTo(pairRoute(id, other))} title="See how this tie changed">since ch ${since}</a> <span class="cbar" title="${esc(story)}">${segments}${ticks}</span></li>`;
}

function connSections(id, all) {
  const by = new Map();
  for (const [other, rows] of all) {
    const g = pairGroup(rows);
    (by.get(g) || by.set(g, []).get(g)).push(connRow(id, other, rows));
  }
  return REL_GROUPS.filter(g => by.has(g.key)).map(g => {
    const items = by.get(g.key), rest = items.slice(CONN.rows);
    const later = rest.length ? expander(`<span class="ifshut">Show all ${items.length}</span><span class="ifopen">Show fewer</span>`, `<ul class="clist">${rest.join('')}</ul>`).join('') : '';
    return `<h4>${swatch(g.key)}${esc(g.label)} <small>${items.length}</small></h4><ul class="clist">${items.slice(0, CONN.rows).join('')}</ul>${later}`;
  }).join('');
}

const PANEL = {font: 13, me: 15, line: 16, row: 40, rx: 130, chars: 22, gap: 12, max: 12, least: 4};
const textWidth = (line, size) => line.length * size * 0.6;

function wrapName(name, width) {
  const words = name.split(' ');
  let first = '';
  while (words.length && `${first} ${words[0]}`.trim().length <= width) first = `${first} ${words.shift()}`.trim();
  if (!first) return {lines: [clip(name, width)], cut: name.length > width};
  const rest = words.join(' ');
  return {lines: rest ? [first, clip(rest, width)] : [first], cut: rest.length > width};
}

function ringPlaces(n) {
  const sides = [[], []];
  for (let i = 0; i < n; i++) sides[i % 2].push(i);
  const ry = (sides[0].length + 1) * PANEL.row / 2, at = [];
  sides.forEach((side, s) => side.forEach((i, k) => {
    const y = (k + 0.5 - side.length / 2) * PANEL.row;
    at[i] = [num((s ? -1 : 1) * PANEL.rx * Math.sqrt(1 - (y / ry) ** 2)), num(y)];
  }));
  return at;
}

function ringLabel(cls, x, y, anchor, size, {lines, cut}, name) {
  const top = y - (lines.length - 1) * PANEL.line / 2 + size * 0.35;
  const spans = lines.map((t, j) => `<tspan x="${x}" y="${num(top + j * PANEL.line)}">${esc(t)}</tspan>`).join('');
  return `<text class="${cls}" x="${x}" y="${num(top)}" text-anchor="${anchor}">${spans}${cut ? `<title>${esc(name)}</title>` : ''}</text>`;
}

function ringSvg(me, drawn) {
  const at = ringPlaces(drawn.length), ext = [[-24, -24], [24, 24]];
  const grow = (x, y) => { ext[0] = [Math.min(ext[0][0], x), Math.min(ext[0][1], y)]; ext[1] = [Math.max(ext[1][0], x), Math.max(ext[1][1], y)]; };
  const nodes = drawn.map((d, i) => {
    const [x, y] = at[i], right = x > 0, name = displayName(D.byId[d.id]), wrap = wrapName(name, PANEL.chars);
    const lx = num(x + (right ? PANEL.gap : -PANEL.gap)), w = Math.max(...wrap.lines.map(t => textWidth(t, PANEL.font)));
    grow(right ? lx + w : lx - w, y - wrap.lines.length * PANEL.line / 2 - 4);
    grow(lx, y + wrap.lines.length * PANEL.line / 2 + 4);
    const words = d.rows.map(relText).join('\n'), d0 = `M0 0L${x} ${y}`;
    return `<a class="ent gnode" data-ent="${d.id}" href="#${hashFor({p: 'e:' + d.id, tab: ''})}" aria-label="${esc(`${name}. ${words}`)}" data-rels="${esc(words)}">`
      + `<path class="hit" d="${d0}"/><path class="spoke${d.aside ? ' aside' : ''}${d.belief ? ' belief' : ''}" d="${d0}" style="stroke:var(--r-${d.group})"/>`
      + `<circle cx="${x}" cy="${y}" r="6" style="fill:${typeColor(D.byId[d.id].type)}"/>`
      + ringLabel('lbl', lx, y, right ? 'start' : 'end', PANEL.font, wrap, name) + '</a>';
  });
  const myName = displayName(me), myWrap = wrapName(myName, PANEL.chars), cy = 22 + (myWrap.lines.length - 1) * PANEL.line / 2;
  const myW = Math.max(...myWrap.lines.map(t => textWidth(t, PANEL.me)));
  grow(-myW / 2, 0);
  grow(myW / 2, cy + myWrap.lines.length * PANEL.line / 2 + 4);
  const [[x0, y0], [x1, y1]] = ext, W = Math.ceil(x1 - x0 + 16), H = Math.ceil(y1 - y0 + 16);
  return `<svg class="graph ego" viewBox="${num(x0 - 8)} ${num(y0 - 8)} ${W} ${H}" width="${W}" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="${esc(myName)} and ${drawn.length} closest connections">`
    + nodes.join('') + `<g class="centre"><circle class="halo" r="15" style="stroke:${typeColor(me.type)}"/><circle r="9" style="fill:${typeColor(me.type)}"/>`
    + ringLabel('lbl me', 0, cy, 'middle', PANEL.me, myWrap, myName) + '</g></svg>';
}

function egoPanel(id) {
  const rows = edgesAt().filter(r => r.role !== 'erased' && (r.source === id || r.target === id));
  if (!rows.length) return '';
  const by = new Map();
  for (const r of rows) {
    const other = r.source === id ? r.target : r.source;
    if (!by.has(other)) by.set(other, []);
    by.get(other).push(r);
  }
  const chapters = rs => new Set(rs.flatMap(r => r.chapters)).size;
  const all = [...by.entries()].sort((a, b) => chapters(b[1]) - chapters(a[1]) || b[1].length - a[1].length
    || displayName(D.byId[a[0]]).localeCompare(displayName(D.byId[b[0]])));
  const drawn = all.length < PANEL.least ? [] : all.slice(0, PANEL.max).map(([other, rs]) => ({id: other, rows: rs, group: kindNow(rs),
    aside: rs.every(r => r.role === 'aside'), belief: rs.every(r => r.status === 'belief')}));
  const marks = [...REL_GROUPS.filter(g => drawn.some(d => d.group === g.key)).map(g => `<span>${swatch(g.key)}${esc(g.label)}</span>`),
    drawn.some(d => d.belief) ? '<span><i class="swatch dash"></i>Suspected</span>' : '',
    drawn.some(d => d.aside) ? '<span><i class="swatch dot"></i>Flashback or aside</span>' : ''].join('');
  const more = drawn.length && all.length > drawn.length ? `<a ${goTo(`graph:${id}`)}>+${all.length - drawn.length} more</a>` : '';
  const figure = drawn.length ? expander(showHide('drawing'), `${ringSvg(D.byId[id], drawn)}<div class="egolegend">${marks}${more}</div>`).join('') : '';
  return `<div class="egobox">${sectionHead('connections', 'Connections')}<div class="conns">${connSections(id, all)}</div>`
    + `<div class="asof">${all.length} connection${all.length > 1 ? 's' : ''} as of chapter ${S.n}. <a ${goTo(`graph:${id}`)}>Open in the graph</a> &middot; <a ${goTo(pairRoute(id, ''))}>How is ${esc(displayName(D.byId[id]))} connected to&hellip;</a> ${figure}</div></div>`;
}

const gkey = el => el.dataset.gn || el.dataset.gb || (el.dataset.for ? 'l:' + el.dataset.for : 'e:' + el.dataset.a + '|' + el.dataset.b);
const GPARTS = '[data-gn],[data-gb],.lbl,path.edge';

function fadeOut(old, view) {
  old.querySelector('.leaving')?.remove();
  const kept = new Set([...view.querySelectorAll(GPARTS)].map(gkey));
  const gone = [...old.querySelectorAll(GPARTS)].filter(el => !kept.has(gkey(el)));
  if (!gone.length) return;
  const layer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  layer.setAttribute('class', 'leaving');
  layer.setAttribute('aria-hidden', 'true');
  for (const el of gone) { el.removeAttribute('tabindex'); layer.appendChild(el); }
  view.prepend(layer);
  setTimeout(() => layer.remove(), 450);
}

function finders(m) {
  if (m.view !== 'path') return {gq: centreRoute};
  return {pa: id => pairRoute(id, m.ends.b), pb: id => pairRoute(m.ends.a, id)};
}

function mountGraph(old) {
  const m = G.model;
  if (m.view === 'story') return mountStory();
  if (m.view === 'matrix') return mountMatrix();
  if (['factions', 'ladder', 'family', 'places', 'masks'].includes(m.view)) return;
  for (const [input, to] of Object.entries(finders(m))) {
    const box = $(input + 'res');
    $(input).addEventListener('input', () => graphSearch($(input), box, to));
    $(input).addEventListener('focus', () => $(input).select());
    $(input).addEventListener('keydown', ev => {
      if (ev.key === 'Enter') box.querySelector('[data-go]')?.click();
      if (ev.key === 'Escape') { $(input).value = ''; box.classList.remove('open'); }
    });
  }
  if (m.view === 'path' && m.ends.a && !m.ends.b) $('pb').focus();
  const svg = $('graph');
  if (!svg) return;
  const view = $('graph-view');
  const els = new Map([...svg.querySelectorAll('[data-gn],[data-gb]')].map(g => [g.dataset.gn || g.dataset.gb, g]));
  const labels = [...svg.querySelectorAll('.lbl')], paths = [...svg.querySelectorAll('.edge')], bands = [...svg.querySelectorAll('.band')];
  const to = new Map([...els].map(([id, g]) => [id, [+g.dataset.x, +g.dataset.y]]));
  const prev = G.shown?.view === m.view ? G.shown : null;
  if (old && prev && prev.focus === m.focus) fadeOut(old, view);
  const shift = (prev && m.focus && prev.focus !== m.focus && prev.pos.get(m.focus)) || [0, 0];
  const from = new Map([...to].map(([id, p]) => {
    const q = prev?.pos.get(id);
    return [id, q ? [q[0] - shift[0], q[1] - shift[1]] : p];
  }));
  const at = new Map(from);
  const fresh = id => !prev?.pos.has(id);
  for (const [id, g] of els) if (fresh(id)) g.classList.add('enter');
  for (const l of labels) if (fresh(l.dataset.for)) l.classList.add('enter');
  for (const p of paths) if (fresh(p.dataset.a) || fresh(p.dataset.b)) p.classList.add('enter');
  G.shown = {view: m.view, focus: m.focus, pos: at};
  const orbit = m.view === 'characters', chain = m.view === 'path', whole = m.view === 'all', still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const longest = Math.max(0, ...labels.map(l => l.textContent.length));
  const {padX, padY, most} = orbit ? {padX: longest * 7 + 24, padY: 36, most: ORBIT.most}
    : chain ? {padX: longest * 3.5 + 24, padY: 44, most: 1.25} : {padX: 70, padY: 40, most: 1.6};
  const {dur, lag} = whole ? {dur: 400, lag: 0} : revealTiming(to.size);
  const order = new Map([...to.keys()].map((id, i) => [id, i]));
  const fit = () => {
    const card = chain && matchMedia('(min-width: 861px)').matches ? $('gcard').offsetWidth + 20 : 0;
    return fitView([...to.values()], svg.clientWidth - card, svg.clientHeight, card, {padX, padY, most});
  };
  let v = prev && G.cam ? {k: G.cam.k, x: G.cam.x + G.cam.k * shift[0], y: G.cam.y + G.cam.k * shift[1]} : G.view || fit();
  const spreadLabels = () => {
    const dots = [...els].map(([id, g]) => { const [x, y] = at.get(id); return {x, y, r: +g.dataset.r}; });
    const items = labels.map(l => { const [x, y] = at.get(l.dataset.for); return {x, y, ox: +l.dataset.ox, oy: +l.dataset.oy, big: l.classList.contains('big'), text: l.textContent, anchor: l.style.textAnchor}; });
    labelSpots(dots, items, v.k, [-v.x, -v.y, svg.clientWidth - v.x, svg.clientHeight - v.y]).forEach(([x, y], i) => { labels[i].setAttribute('x', x); labels[i].setAttribute('y', y); });
  };
  const homeK = fit().k;
  let hovered = null, litUp = null;
  const nameLabels = () => {
    const items = labels.map(l => { const [x, y] = at.get(l.dataset.for); return {id: l.dataset.for, x: x + +l.dataset.ox, y: y + +l.dataset.oy, w: l.textContent.length * 7 + 4, anchor: l.style.textAnchor, main: !l.classList.contains('minor')}; });
    const shown = shownNames(items, v.k, v.k >= homeK * NAMES_AT, hovered, litUp);
    for (const l of labels) l.classList.toggle('hide', !shown.has(l.dataset.for));
  };
  const placeLabels = whole ? nameLabels : spreadLabels;
  let raf = 0;
  const apply = () => {
    view.setAttribute('transform', `translate(${v.x} ${v.y}) scale(${v.k})`);
    svg.style.setProperty('--k', v.k);
    G.cam = v;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(placeLabels);
  };
  const draw = () => {
    for (const [id, g] of els) { const [x, y] = at.get(id); g.setAttribute('transform', `translate(${num(x)} ${num(y)})`); }
    for (const l of labels) { const [x, y] = at.get(l.dataset.for); l.setAttribute('x', num(x + +l.dataset.ox)); l.setAttribute('y', num(y + +l.dataset.oy)); }
    for (const p of paths) p.setAttribute('d', curve(at.get(p.dataset.a), at.get(p.dataset.b), +p.dataset.k));
    for (const b of bands) {
      const [d, width, [x, y]] = bandPath(b.dataset.members.split(' ').map(id => at.get(id)), +b.dataset.r);
      b.children[0].setAttribute('d', d);
      b.children[0].setAttribute('stroke-width', width);
      b.querySelector('text')?.setAttribute('x', x);
      b.querySelector('text')?.setAttribute('y', y);
    }
  };
  const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  const glide = target => {
    const start = performance.now(), v0 = v;
    cancelAnimationFrame(G.glide);
    const tick = now => {
      const T = still ? Infinity : now - start, t = ease(Math.min(1, T / dur));
      for (const [id, p] of to) {
        const f = from.get(id), u = ease(Math.min(1, Math.max(0, (T - lag * order.get(id)) / dur)));
        at.set(id, [f[0] + (p[0] - f[0]) * u, f[1] + (p[1] - f[1]) * u]);
      }
      v = {k: v0.k + (target.k - v0.k) * t, x: v0.x + (target.x - v0.x) * t, y: v0.y + (target.y - v0.y) * t};
      draw();
      apply();
      if (T < dur + lag * (to.size - 1)) G.glide = requestAnimationFrame(tick);
    };
    G.glide = requestAnimationFrame(tick);
  };
  draw();
  apply();
  if (prev) glide(G.view || fit());
  const zoom = (f, cx, cy) => {
    cancelAnimationFrame(G.glide);
    const k = Math.min(6, Math.max(0.1, v.k * f));
    v = G.view = {k, x: cx - (cx - v.x) * k / v.k, y: cy - (cy - v.y) * k / v.k};
    apply();
  };
  G.refit = () => { if (svg.isConnected && !G.view) glide(fit()); };
  G.zoom = f => {
    if (f === 'fit') { G.view = null; return glide(fit()); }
    zoom(+f, svg.clientWidth / 2, svg.clientHeight / 2);
  };
  const light = id => {
    svg.classList.toggle('hl', !!id);
    hovered = id;
    litUp = null;
    if (!id) return whole && nameLabels();
    const on = new Set([id]);
    for (const p of paths) {
      const hit = p.dataset.a === id || p.dataset.b === id;
      p.classList.toggle('on', hit);
      if (hit) { on.add(p.dataset.a); on.add(p.dataset.b); }
    }
    for (const [key, g] of els) g.classList.toggle('on', on.has(key));
    for (const l of labels) l.classList.toggle('on', on.has(l.dataset.for));
    litUp = on;
    if (whole) nameLabels();
    if (D.byId[id]) $('gcard').innerHTML = graphCard(id);
  };
  G.light = light;
  const lit = ev => ev.target.closest('[data-gn],[data-gb]');
  svg.addEventListener('pointerover', ev => { const g = lit(ev); if (g) light(g.dataset.gn || g.dataset.gb); });
  svg.addEventListener('pointerout', ev => { if (lit(ev) && !ev.relatedTarget?.closest?.('[data-gn],[data-gb]')) light(null); });
  svg.addEventListener('focusin', ev => { const g = lit(ev); if (g) light(g.dataset.gn || g.dataset.gb); });
  svg.addEventListener('focusout', () => light(null));
  if (G.refocus) { svg.querySelector(`[data-gn="${G.refocus}"]`)?.focus(); G.refocus = null; }
  const ptrs = new Map();
  let moved = 0, pinch = null;
  const local = ev => { const b = svg.getBoundingClientRect(); return [ev.clientX - b.left, ev.clientY - b.top]; };
  svg.addEventListener('pointerdown', ev => { ptrs.set(ev.pointerId, local(ev)); moved = 0; pinch = null; });
  svg.addEventListener('pointermove', ev => {
    if (!ptrs.has(ev.pointerId)) return;
    const [x, y] = local(ev), [px, py] = ptrs.get(ev.pointerId);
    ptrs.set(ev.pointerId, [x, y]);
    if (ptrs.size === 2) {
      const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (pinch) zoom(d / pinch, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
      pinch = d;
      moved += 10;
      return;
    }
    moved += Math.abs(x - px) + Math.abs(y - py);
    if (moved > 4) { cancelAnimationFrame(G.glide); v = G.view = {...v, x: v.x + x - px, y: v.y + y - py}; apply(); }
  });
  const up = ev => { ptrs.delete(ev.pointerId); pinch = null; };
  svg.addEventListener('pointerup', up);
  svg.addEventListener('pointercancel', up);
  svg.addEventListener('pointerleave', up);
  svg.addEventListener('click', ev => { if (moved > 4) { ev.stopPropagation(); ev.preventDefault(); } }, true);
  svg.addEventListener('wheel', ev => { ev.preventDefault(); const [x, y] = local(ev); zoom(Math.exp(-ev.deltaY * 0.0015), x, y); }, {passive: false});
}

const NAMES_AT = 1.6;

function fitView(pts, W, H, left, {padX, padY, most}) {
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const k = Math.min((W - 2 * Math.min(padX, W / 5)) / (x1 - x0), (H - 2 * padY) / (y1 - y0), most);
  return {k, x: left + W / 2 - (x0 + x1) / 2 * k, y: H / 2 - (y0 + y1) / 2 * k};
}

const REVEAL = {dur: 250, stagger: 150, lag: 20};
const revealTiming = n => ({dur: REVEAL.dur, lag: Math.min(REVEAL.lag, REVEAL.stagger / Math.max(1, n - 1))});

function labelSpots(dots, items, k, bounds) {
  const taken = dots.map(({x, y, r}) => [(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k]);
  const area = (c, o) => Math.max(0, Math.min(c[2], o[2]) - Math.max(c[0], o[0])) * Math.max(0, Math.min(c[3], o[3]) - Math.max(c[1], o[1]));
  return items.map(({x, y, ox, oy, big, text, anchor}) => {
    const d = Math.hypot(x, y) || 1, [ux, uy] = big ? [0, 1] : [x / d, y / d], w = text.length * (big ? 7.6 : 7) + 4;
    const boxAt = ([s, t]) => {
      const lx = (x + ox) * k + ux * s - uy * t, ly = (y + oy) * k + uy * s + ux * t, x0 = anchor === 'start' ? lx : anchor === 'end' ? lx - w : lx - w / 2;
      return [x0, ly - 9, x0 + w, ly + 9, lx, ly];
    };
    const off = c => (c[2] - c[0]) * (c[3] - c[1]) - area(c, bounds);
    const clash = c => off(c) + taken.reduce((sum, o) => sum + area(c, o), 0);
    let best = boxAt(LABEL_NUDGES[0]);
    for (const n of LABEL_NUDGES.slice(1)) {
      if (!clash(best)) break;
      const c = boxAt(n);
      if (clash(c) < clash(best)) best = c;
    }
    taken.push(best);
    return [num(best[4] / k), num(best[5] / k)];
  });
}

function shownNames(items, k, zoomed, hovered, lit) {
  const rank = it => it.id === hovered ? 0 : lit?.has(it.id) ? 1 : it.main ? 2 : 3;
  const taken = [], shown = new Set();
  for (const it of [...items].sort((a, b) => rank(a) - rank(b))) {
    if (rank(it) === 3 && !zoomed) continue;
    const left = it.x * k - (it.anchor === 'end' ? it.w : it.anchor === 'start' ? 0 : it.w / 2), box = [left, it.y * k - 8, left + it.w, it.y * k + 8];
    if (it.id !== hovered && taken.some(o => box[0] < o[2] && box[2] > o[0] && box[1] < o[3] && box[3] > o[1])) continue;
    taken.push(box);
    shown.add(it.id);
  }
  return shown;
}

function moveCentre(p) {
  Object.assign(G, {limit: STEP, open: new Set(), view: null});
  S.p = p;
  writeHash();
  render();
}

function recentre(id) {
  if (id !== G.model.focus) moveCentre(centreRoute(id));
}

const openPage = id => { G.click = null; go({p: 'e:' + id, tab: ''}); };

function graphClick(ev, act) {
  let el;
  const now = performance.now(), last = G.click;
  if (last && act('#graph') && now - last.t < 400 && Math.hypot(ev.clientX - last.x, ev.clientY - last.y) < 12) { ev.preventDefault(); openPage(last.id); return true; }
  if ((el = act('[data-gn]')) && ev.pointerType === 'touch' && G.tapped !== el.dataset.gn) { G.tapped = el.dataset.gn; G.light?.(el.dataset.gn); return true; }
  if ((el = act('.edge[data-a]'))) { go({p: pairRoute(el.dataset.a, el.dataset.b)}); return true; }
  if ((el = act('[data-gn]'))) { G.tapped = null; G.click = {id: el.dataset.gn, t: now, x: ev.clientX, y: ev.clientY}; recentre(el.dataset.gn); return true; }
  if ((el = act('[data-gb]'))) { G.open.add(el.dataset.gb); render(); return true; }
  if (act('[data-gmore]')) { G.limit += STEP; render(); return true; }
  if (act('[data-gall]')) { G.limit = Infinity; render(); return true; }
  if (act('[data-gback]')) { ev.preventDefault(); moveCentre(GRAPH_VIEWS.characters.route); return true; }
  if ((el = act('[data-gc]'))) { ev.preventDefault(); recentre(el.dataset.gc); return true; }
  if ((el = act('[data-gopen]'))) { ev.preventDefault(); openPage(el.dataset.gopen); return true; }
  return false;
}

function graphKey(ev) {
  const el = ev.target.closest?.('[data-gn],[data-gb]');
  if (!el) return false;
  const press = ev.key === 'Enter' || ev.key === ' ';
  if (press && el.dataset.gb) { G.open.add(el.dataset.gb); render(); }
  else if (press) { G.refocus = el.dataset.gn; recentre(el.dataset.gn); }
  else if ((ev.key === 'o' || ev.key === 'O') && el.dataset.gn) openPage(el.dataset.gn);
  else return false;
  ev.preventDefault();
  return true;
}

function graphSearch(input, box, to) {
  if (!searchKey(input.value)) return box.classList.remove('open');
  const linked = new Set(edgesAt().flatMap(r => [r.source, r.target]));
  const hits = findEntries(input.value, D.entities.filter(e => vis(e) && linked.has(e.id)), (a, b) => displayName(a).localeCompare(displayName(b)));
  box.innerHTML = hits.slice(0, 12).map((h, i) => `<div data-go="${to(h.e.id)}" class="${i ? '' : 'sel'}" role="option"><span>${hitName(h)}</span><small>${esc(h.e.type)}</small></div>`).join('') || '<div class="muted">No connected entry matches up to this chapter</div>';
  box.classList.add('open');
}

const STORY = {limit: 20, centre: 0.3, sweeps: 3, away: 5, inner: 14, gap: 30, top: 52, pad: 150, col: [3, 10, 28, 48], hues: 6};
const storyRoute = id => 'graph:story' + (id ? ':' + id : '');
let storyCache = {n: -1};

function storyData() {
  if (storyCache.n === S.n) return storyCache;
  const seen = new Map(), pairs = new Map();
  const mark = (id, c, via) => {
    const at = seen.get(id) || seen.set(id, new Map()).get(id);
    (at.get(c) || at.set(c, new Set()).get(c)).add(via);
  };
  for (const e of D.entities) for (const c of e.present || []) if (c <= S.n && vis(D.byId[live(e.id)])) mark(live(e.id), c, e.id);
  const {map, plain, re} = linker();
  const owner = (id, name) => (D.parts[id] || []).find(p => [D.byId[p].name, ...D.byId[p].aliases.map(a => a.name)].includes(name)) || id;
  const named = (text, c) => re ? [...text.matchAll(re)].filter(m => (!plain[m[0]] || plain[m[0]].has(c)) && isPerson(map[m[0]])).map(m => [map[m[0]], owner(map[m[0]], m[0])]) : [];
  const meet = (ids, c) => {
    for (const a of ids) for (const b of ids) if (a < b && vis(D.byId[a]) && vis(D.byId[b])) (pairs.get(c) || pairs.set(c, new Set()).get(c)).add(a + '|' + b);
  };
  for (const r of until(D.relations)) meet([live(r.source), live(r.target)].filter(isPerson), r.chapter);
  for (const f of until(D.facts)) if (isPerson(live(f.entity))) {
    meet([live(f.entity), ...named([f.claim, ...(f.unverified ? [] : f.quotes || [])].join(' | '), f.chapter).map(([id]) => id)], f.chapter);
  }
  for (const c of until(D.chapters, 'n')) for (const sentence of c.synopsis.split(/(?<=[.!?])\s+/)) {
    const found = named(sentence, c.n);
    for (const [id, via] of found) mark(id, c.n, via);
    meet(found.map(([id]) => id), c.n);
  }
  storyCache = {n: S.n, seen, pairs};
  return storyCache;
}

function deathOf(e) {
  const s = e.profile && currentStatus(e.profile);
  return s?.value === 'dead' && s.basis === 'observed' ? s.chapter : null;
}
const fate = id => ({died: isPerson(id) ? deathOf(D.byId[id]) : null, fresh: D.byId[id].first === S.n});
const newTag = chapter => chapter === S.n ? ' <span class="newtag">new</span>' : '';
function who(id) {
  const {died} = fate(live(id));
  return died == null ? entLink(id) : `<span class="dead" title="Died ch ${died}">${entLink(id)} <span class="dagger">${DAGGER}</span></span>`;
}

function storyLines(seen, ids) {
  return ids.map(id => {
    const e = D.byId[id], at = seen.get(id), chapters = [...at.keys()].sort((a, b) => a - b);
    const start = chapters[0], death = deathOf(e), end = Math.max(start, death ?? chapters.at(-1));
    const first = new Map();
    for (const c of chapters) for (const via of at.get(c)) if (!first.has(via)) first.set(via, c);
    const known = c => [...first].filter(([p, f]) => f <= c && (p === id || c < D.byId[p].merged.chapter))
      .sort((x, y) => y[1] - x[1] || (x[0] === id ? -1 : y[0] === id ? 1 : cmp(x[0], y[0])))[0]?.[0] ?? id;
    const segments = [];
    for (let c = start; c <= end; c++) {
      const label = nameAt(D.byId[known(c)], c) || displayName(e);
      if (segments.at(-1)?.label === label) segments.at(-1).to = c;
      else segments.push({from: c, to: c, label});
    }
    const present = chapters.filter(c => c <= end), spans = [];
    for (const c of present.includes(end) ? present : [...present, end]) {
      if (spans.length && c - spans.at(-1).to <= STORY.away) spans.at(-1).to = c;
      else spans.push({from: c, to: c});
    }
    return {id, start, end, death, present, spans, segments};
  });
}

function storyColumns(lines, pairs, rank) {
  const cols = [];
  for (let c = Math.min(...lines.map(l => l.start)); c <= S.n; c++) {
    const active = lines.filter(l => l.spans.some(s => s.from <= c && c <= s.to)).map(l => l.id);
    const here = new Set(lines.filter(l => l.present.includes(c)).map(l => l.id));
    const root = new Map(active.map(id => [id, id]));
    const find = id => root.get(id) === id ? id : find(root.get(id));
    for (const key of pairs.get(c) || []) {
      const [a, b] = key.split('|');
      if (here.has(a) && here.has(b)) root.set(find(a), find(b));
    }
    const groups = new Map();
    for (const id of active) (groups.get(find(id)) || groups.set(find(id), []).get(find(id))).push(id);
    const byRank = (a, b) => rank.get(a) - rank.get(b);
    cols.push({c, groups: [...groups.values()].map(g => g.sort(byRank)).sort((g, h) => byRank(g[0], h[0]))});
  }
  return cols;
}

function storyOrder(cols, rank) {
  const index = col => new Map(col.groups.flat().map((id, i) => [id, i]));
  const sweep = (col, near) => {
    const own = index(col), at = id => near.has(id) ? near.get(id) : own.get(id);
    const key = g => g.reduce((s, id) => s + at(id), 0) / g.length;
    col.groups = col.groups.map(g => g.sort((a, b) => at(a) - at(b) || rank.get(a) - rank.get(b)))
      .sort((g, h) => key(g) - key(h) || rank.get(g[0]) - rank.get(h[0]));
  };
  for (let pass = 0; pass < STORY.sweeps; pass++) {
    for (let i = 1; i < cols.length; i++) sweep(cols[i], index(cols[i - 1]));
    for (let i = cols.length - 2; i >= 0; i--) sweep(cols[i], index(cols[i + 1]));
  }
  for (let i = 1; i < cols.length; i++) sweep(cols[i], index(cols[i - 1]));
  return cols;
}

function settle(targets) {
  const pools = [];
  for (const [t, w] of targets) {
    pools.push({sum: t * w, w, n: 1});
    while (pools.length > 1 && pools.at(-2).sum / pools.at(-2).w >= pools.at(-1).sum / pools.at(-1).w) {
      const last = pools.pop();
      Object.assign(pools.at(-1), {sum: pools.at(-1).sum + last.sum, w: pools.at(-1).w + last.w, n: pools.at(-1).n + last.n});
    }
  }
  return pools.flatMap(p => Array(p.n).fill(p.sum / p.w));
}

function storyYs(cols) {
  const ys = new Map();
  let last = new Map();
  for (const {c, groups} of cols) {
    let floor = 0;
    const blocks = groups.map(g => {
      const old = g.map((id, i) => last.has(id) ? last.get(id) - i * STORY.inner - floor : null).filter(t => t != null);
      const block = {g, floor, old};
      floor += (g.length - 1) * STORY.inner + STORY.gap;
      return block;
    });
    const middle = -(floor - STORY.gap) / 2;
    const z = settle(blocks.map(b => b.old.length ? [b.old.reduce((s, t) => s + t, 0) / b.old.length, b.old.length] : [middle, STORY.centre]));
    const here = new Map();
    blocks.forEach((b, k) => b.g.forEach((id, i) => {
      const y = Math.round(z[k] + b.floor + i * STORY.inner);
      here.set(id, y);
      (ys.get(id) || ys.set(id, []).get(id)).push([c, y]);
    }));
    last = here;
  }
  const top = Math.min(...[...ys.values()].flat().map(p => p[1]));
  for (const pts of ys.values()) for (const p of pts) p[1] -= top;
  return ys;
}

function storyRanked() {
  const {seen} = storyData();
  return storyLines(seen, [...seen.keys()].filter(id => vis(D.byId[id])))
    .sort((a, b) => b.present.length - a.present.length || a.start - b.start || byName(a.id, b.id) || cmp(a.id, b.id));
}

function storyAt(arg) {
  const {pairs} = storyData();
  const everyone = storyRanked();
  const rank = new Map(everyone.map((l, i) => [l.id, i]));
  const focus = arg && rank.has(live(arg)) ? live(arg) : null;
  const st = G.story;
  const lines = everyone.filter((l, i) => l.id === focus || st.add.has(l.id) || (i < STORY.limit && !st.drop.has(l.id)));
  const candidates = everyone.map(l => l.id).filter(id => !lines.some(l => l.id === id));
  if (!lines.length) return {view: 'story', focus, lines, groups: [], candidates, from: S.n};
  const cols = storyOrder(storyColumns(lines, pairs, rank), rank);
  const ys = storyYs(cols);
  for (const l of lines) l.points = ys.get(l.id);
  const groups = cols.flatMap(({c, groups}) => groups.filter(g => g.length > 1).map(members => ({chapter: c, members})));
  return {view: 'story', focus, lines, groups, candidates, from: cols[0].c, height: Math.max(...lines.flatMap(l => l.points.map(p => p[1])))};
}

function storyGeometry(m) {
  const span = S.n - m.from + 1, room = Math.max(320, $('main').clientWidth - 2 * STORY.pad - 2);
  const [least, low, high, most] = STORY.col, fit = room / span, want = G.story.col;
  const k = Math.min(most, Math.max(least, want === 'fit' ? fit : want ?? Math.min(high, Math.max(low, fit))));
  return {col: k, x: c => STORY.pad + (c - m.from + .5) * k, width: 2 * STORY.pad + span * k, height: STORY.top + m.height + 40};
}

function storyPath(pts, x, half) {
  return pts.map(([c, y], i) => {
    const flat = `L${num(x(c) + half)} ${y}`;
    if (!i) return `M${num(x(c) - half)} ${y}${flat}`;
    const [pc, py] = pts[i - 1], mid = num((x(pc) + half + x(c) - half) / 2);
    return `C${mid} ${py} ${mid} ${y} ${num(x(c) - half)} ${y}${flat}`;
  }).join('');
}

function storyRuns(line) {
  const runs = [];
  for (const c of line.present) {
    if (runs.at(-1)?.at(-1) === c - 1) runs.at(-1).push(c);
    else runs.push([c]);
  }
  return runs;
}

function storyAxis(m, g) {
  const step = [1, 2, 5, 10, 20, 25, 50, 100].find(s => s * g.col >= 34) || 100;
  const ticks = [];
  for (let c = m.from; c <= S.n; c++) if (c === m.from || c === S.n || (c % step === 0 && c - m.from >= step / 2 && S.n - c >= step / 2)) ticks.push(c);
  const tickSvg = ticks.map(c => `<a ${goTo(`ch:${c}`)}><text class="stick" x="${num(g.x(c))}" y="${STORY.top - 12}">${c}</text></a>`).join('');
  const arcs = D.volumes.flatMap(v => v.arcs).filter(a => a.start <= S.n && a.end >= m.from);
  const arcSvg = arcs.map(a => {
    const x0 = g.x(Math.max(a.start, m.from)) - g.col / 2, x1 = g.x(Math.min(a.end, S.n)) + g.col / 2;
    const name = a.end <= S.n ? clip(a.name, Math.floor((x1 - x0 - 8) / 6.4)) : '';
    return `<g class="sarc"><line x1="${num(x0)}" x2="${num(x0)}" y1="4" y2="${g.height}"/>${name.length > 3 ? `<text x="${num(x0 + 5)}" y="14">${esc(name)}</text>` : ''}</g>`;
  }).join('');
  const vols = D.volumes.filter(v => v.from > m.from && v.from <= S.n).map(v => {
    const x0 = num(g.x(v.from) - g.col / 2);
    return `<g class="svol"><line x1="${x0}" x2="${x0}" y1="0" y2="${g.height}"/><a ${goTo('v:' + v.id)}><text x="${x0 + 5}" y="${STORY.top - 26}">${esc(v.name)}</text></a></g>`;
  }).join('');
  return arcSvg + vols + tickSvg;
}

function storySvg(m, g) {
  const half = num(g.col * .28), top = STORY.top;
  const at = (l, c) => l.points.find(p => p[0] === c);
  const shift = pts => pts.map(([c, y]) => [c, y + top]);
  const meets = new Set(m.focus ? m.groups.filter(gr => gr.members.includes(m.focus)).flatMap(gr => gr.members) : []);
  const boxes = [];
  for (const gr of m.groups) {
    const ys = gr.members.map(id => at(m.lines.find(l => l.id === id), gr.chapter)[1] + top);
    const box = {from: gr.chapter, to: gr.chapter, y0: Math.min(...ys) - 6, y1: Math.max(...ys) + 6, key: gr.members.join(' '), mine: gr.members.includes(m.focus)};
    const last = boxes.find(b => b.to === gr.chapter - 1 && b.key === box.key && b.y0 === box.y0 && b.y1 === box.y1);
    if (last) last.to = gr.chapter;
    else boxes.push(box);
  }
  const boxSvg = boxes.map(b => `<rect class="sgroup${b.mine ? ' mine' : ''}" x="${num(g.x(b.from) - g.col / 2 + 1)}" y="${b.y0}" width="${num((b.to - b.from + 1) * g.col - 2)}" height="${b.y1 - b.y0}" rx="5"/>`).join('');
  const taken = [];
  const fits = (x, y, text, anchor) => {
    const w = text.length * 6.4 + 4, x0 = anchor === 'end' ? x - w : x, box = [x0, y - 7, x0 + w, y + 7];
    if (taken.some(o => box[0] < o[2] && box[2] > o[0] && box[1] < o[3] && box[3] > o[1])) return false;
    taken.push(box);
    return true;
  };
  const place = (l, x, y, text, anchor, cls, nudges) => {
    const dy = nudges.find(d => fits(x, y + d, text, anchor));
    return dy == null ? '' : `<a class="ent slbl${cls}" data-ent="${l.id}" href="#${esc(hashFor({p: 'e:' + l.id, tab: ''}))}"><text x="${num(x)}" y="${y + dy + 4}" style="text-anchor:${anchor}">${esc(text)}</text></a>`;
  };
  const labelAt = (l, c) => l.segments.find(sg => sg.from <= c && c <= sg.to).label;
  const wanted = m.lines.flatMap((l, rank) => {
    const pts = shift(l.points), [ec, ey] = pts.at(-1), y = c => at(l, c)[1] + top, end = labelAt(l, ec), last = l.spans.at(-1);
    const short = (last.to - last.from) * g.col < 120;
    return [
      {l, tier: l.death != null ? 0 : 1, rank, x: g.x(ec) + half + (l.death != null ? 10 : 6), y: ey, text: end, anchor: 'start', cls: ' send', nudges: [0, -6, 6]},
      ...l.spans.filter(sp => !(sp === last && short && labelAt(l, sp.from) === end))
        .map((sp, k) => ({l, tier: k ? 3 : 2, rank, x: g.x(sp.from) - half - 6, y: y(sp.from), text: labelAt(l, sp.from), anchor: 'end', cls: '', nudges: [0, -8, 8]})),
      ...l.segments.slice(1).filter(sg => at(l, sg.from) && !l.spans.some(sp => sp.from === sg.from))
        .map(sg => ({l, tier: 4, rank, x: g.x(sg.from) - half, y: y(sg.from) - 10, text: sg.label, anchor: 'start', cls: ' sname', nudges: [0, -6]})),
    ];
  }).sort((p, q) => (q.l.id === m.focus) - (p.l.id === m.focus) || p.tier - q.tier || p.rank - q.rank);
  const labels = new Map(m.lines.map(l => [l.id, '']));
  for (const w of wanted) labels.set(w.l.id, labels.get(w.l.id) + place(w.l, w.x, w.y, w.text, w.anchor, w.cls, w.nudges));
  const lines = m.lines.map((l, i) => {
    const pts = shift(l.points), [ec, ey] = pts.at(-1);
    const within = sp => pts.filter(p => sp.from <= p[0] && p[0] <= sp.to);
    const spans = l.spans.map(sp => {
      const d = storyPath(within(sp), g.x, half), [sc, sy] = within(sp)[0];
      return `<path class="sbase" d="${d}"/><circle class="sstart" cx="${num(g.x(sc) - half)}" cy="${sy}" r="2.6"/>`;
    }).join('');
    const solid = storyRuns(l).map(run => `<path class="son" d="${storyPath(pts.filter(p => run.includes(p[0])), g.x, half)}"/>`).join('');
    const death = l.death != null ? `<g class="sdeath" data-death="${l.id}" transform="translate(${num(g.x(ec) + half)} ${ey})"><path d="M-4 -4L4 4M4 -4L-4 4"/><title>${esc(labelAt(l, ec))} died, ch ${l.death}</title></g>` : '';
    const cls = l.id === m.focus ? ' focus' : meets.has(l.id) ? ' near' : '';
    return `<g class="sline${cls}" data-line="${l.id}" style="--c:var(--s${i % STORY.hues + 1})">${spans}${solid}${death}${labels.get(l.id)}</g>`;
  }).join('');
  const lead = m.focus ? `${displayName(D.byId[m.focus])}'s storyline` : 'Storylines';
  return `<svg class="story${m.focus ? ' hasfocus' : ''}" id="story" width="${num(g.width)}" height="${num(g.height)}" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="${esc(lead)} to chapter ${S.n}">`
    + `<g class="saxis">${storyAxis(m, g)}</g><g class="sgroups">${boxSvg}</g><g class="slines">${lines}</g></svg>`;
}

function storyPicker(m) {
  const chip = id => {
    const on = id === m.focus, name = esc(displayName(D.byId[id]));
    return `<span class="schip${on ? ' on' : ''}" style="--c:var(--s${m.lines.findIndex(l => l.id === id) % STORY.hues + 1})"><a data-sfocus="${id}" href="#${esc(hashFor({p: storyRoute(on ? '' : id)}))}" aria-pressed="${on}">${name}</a><button type="button" data-sdrop="${id}" aria-label="Remove ${name}">&times;</button></span>`;
  };
  const reset = G.story.add.size || G.story.drop.size ? `<button type="button" class="linkbtn" data-sreset>Back to the top ${STORY.limit}</button>` : '';
  return `<div class="spick">${m.lines.map(l => chip(l.id)).join('')}<div class="searchwrap"><input id="sq" type="search" placeholder="Add a character" autocomplete="off" aria-label="Add a character"><div class="results" id="sqres" role="listbox"></div></div>${reset}</div>`;
}

function renderStory(m) {
  const g = m.lines.length ? storyGeometry(m) : null;
  const shown = m.lines.length, all = shown + m.candidates.length;
  const subtitle = shown ? `${shown === all ? `All ${all}` : `${shown} of ${all}`} characters from chapter ${m.from} to ${S.n}${m.focus ? `, following ${entLink(m.focus)}` : ''}` : `No characters by chapter ${S.n}`;
  const zoom = `<div class="szoom"><button class="iconbtn" data-sz="1.5" aria-label="Widen chapters">+</button><button class="iconbtn" data-sz="0.67" aria-label="Narrow chapters">&minus;</button><button class="iconbtn" data-sz="fit" aria-label="Fit every chapter">&#9635;</button></div>`;
  const body = g ? `<div class="storywrap"><div class="sscroll" id="sscroll">${storySvg(m, g)}</div>${zoom}<div class="stip" id="stip" aria-hidden="true"></div></div>` : '';
  return `<div class="crumbs"><a ${goTo('home')}>Home</a></div><h1>Graph</h1>${graphTabs('story')}<div class="subtitle">${subtitle}</div>${storyPicker(m)}${body}
  <p class="muted glegend">Each line is a character from the chapter they first appear. A line runs bold through chapters that mention them, thin while they are away, and breaks after ${STORY.away} chapters away. Lines run side by side in a shaded band when a chapter puts those characters together, and a cross ends a line at a death. Hover a line to see who is with them, click it or a name above to follow that character, and click a name on the chart to open their page. Scroll sideways to move through the chapters.</p>`;
}

function storyClick(ev, act) {
  let el;
  const st = G.story, m = G.model;
  const redraw = () => { render(); return true; };
  if ((el = act('[data-sfocus]'))) {
    ev.preventDefault();
    S.p = storyRoute(m.focus === el.dataset.sfocus ? '' : el.dataset.sfocus);
    writeHash();
    return redraw();
  }
  if ((el = act('[data-sdrop]'))) {
    const id = el.dataset.sdrop;
    st.add.delete(id);
    st.drop.add(id);
    if (m.focus === id) { S.p = storyRoute(''); writeHash(); }
    return redraw();
  }
  if ((el = act('[data-sadd]'))) {
    st.drop.delete(el.dataset.sadd);
    st.add.add(el.dataset.sadd);
    return redraw();
  }
  if (act('[data-sreset]')) { st.add.clear(); st.drop.clear(); return redraw(); }
  if ((el = act('[data-sz]'))) {
    const now = storyGeometry(m).col;
    st.col = el.dataset.sz === 'fit' ? 'fit' : now * +el.dataset.sz;
    return redraw();
  }
  return false;
}

function storySearch(input, box, m) {
  if (!searchKey(input.value)) return box.classList.remove('open');
  const hits = findEntries(input.value, m.candidates.map(id => D.byId[id])).slice(0, 12);
  box.innerHTML = hits.map((h, i) => `<div data-sadd="${h.e.id}" class="${i ? '' : 'sel'}" role="option"><span>${hitName(h)}</span></div>`).join('') || '<div class="muted">No other character matches up to this chapter</div>';
  box.classList.add('open');
}

function mountStory() {
  const m = G.model, st = G.story, wrap = $('sscroll'), svg = $('story'), tip = $('stip');
  const input = $('sq'), box = $('sqres');
  input.addEventListener('input', () => storySearch(input, box, m));
  input.addEventListener('keydown', ev => {
    if (ev.key === 'Enter') box.querySelector('[data-sadd]')?.click();
    if (ev.key === 'Escape') { input.value = ''; box.classList.remove('open'); }
  });
  if (!svg) return;
  const g = storyGeometry(m);
  const chapterAt = x => Math.min(S.n, Math.max(m.from, Math.round((x - STORY.pad) / g.col - .5) + m.from));
  if (st.n !== S.n || st.center == null) wrap.scrollLeft = wrap.scrollWidth;
  else wrap.scrollLeft = g.x(st.center) - wrap.clientWidth / 2;
  st.n = S.n;
  wrap.addEventListener('scroll', () => { st.center = chapterAt(wrap.scrollLeft + wrap.clientWidth / 2); });
  const rows = new Map(m.lines.map(l => [l.id, new Map(l.points)]));
  const mates = new Map();
  for (const gr of m.groups) for (const id of gr.members) mates.set(id + '@' + gr.chapter, gr.members.filter(x => x !== id));
  const nearest = ev => {
    const b = svg.getBoundingClientRect(), y = ev.clientY - b.top - STORY.top, c = chapterAt(ev.clientX - b.left);
    const near = m.lines.filter(l => rows.get(l.id).has(c)).map(l => [Math.abs(rows.get(l.id).get(c) - y), l]).sort((p, q) => p[0] - q[0])[0];
    return near && near[0] <= STORY.inner ? [near[1], c] : [];
  };
  const show = ev => {
    const [l, c] = nearest(ev);
    svg.querySelectorAll('.sline.on').forEach(el => el.classList.remove('on'));
    if (!l) { svg.classList.remove('hl'); tip.classList.remove('show'); return; }
    const company = mates.get(l.id + '@' + c) || [];
    const name = [...l.segments].reverse().find(s => s.from <= c).label;
    svg.classList.add('hl');
    svg.querySelector(`[data-line="${l.id}"]`).classList.add('on');
    tip.innerHTML = `<b>${esc(name)}</b> &middot; ch ${c}${company.length ? `<br>with ${company.map(id => esc(displayName(D.byId[id]))).join(', ')}` : l.present.includes(c) ? '' : '<br><span class="muted">not in this chapter</span>'}`;
    const w = wrap.getBoundingClientRect();
    tip.style.left = Math.min(ev.clientX - w.left + 14, w.width - 220) + 'px';
    tip.style.top = (ev.clientY - w.top + 14) + 'px';
    tip.classList.add('show');
  };
  svg.addEventListener('pointermove', show);
  svg.addEventListener('pointerleave', () => { svg.classList.remove('hl'); tip.classList.remove('show'); });
  svg.addEventListener('click', ev => {
    const [l] = ev.target.closest('a') ? [] : nearest(ev);
    if (!l) return;
    S.p = storyRoute(m.focus === l.id ? '' : l.id);
    writeHash();
    render();
  });
  let drag = null;
  wrap.addEventListener('pointerdown', ev => { if (ev.pointerType === 'mouse' && !ev.button) drag = {x: ev.clientX, left: wrap.scrollLeft, moved: 0}; });
  wrap.addEventListener('pointermove', ev => {
    if (!drag) return;
    drag.moved = Math.abs(ev.clientX - drag.x);
    if (drag.moved > 4) wrap.scrollLeft = drag.left - (ev.clientX - drag.x);
  });
  const stop = () => { setTimeout(() => { drag = null; }); };
  wrap.addEventListener('pointerup', stop);
  wrap.addEventListener('pointerleave', stop);
  wrap.addEventListener('click', ev => { if (drag?.moved > 4) { ev.stopPropagation(); ev.preventDefault(); } }, true);
}

const MATRIX = {limit: 60, decay: 0.5, rows: 4};

function matrixAt() {
  const rows = edgesAt().filter(r => r.role !== 'erased' && isPerson(r.source) && isPerson(r.target));
  const partners = new Map();
  for (const r of rows) for (const [x, y] of [[r.source, r.target], [r.target, r.source]]) (partners.get(x) || partners.set(x, new Set()).get(x)).add(y);
  let ranked = storyRanked().map(l => l.id).filter(id => partners.has(id));
  for (;;) {
    const top = new Set(ranked.slice(0, MATRIX.limit));
    const kept = ranked.filter((id, i) => i >= MATRIX.limit || [...partners.get(id)].some(p => top.has(p)));
    if (kept.length === ranked.length) break;
    ranked = kept;
  }
  const top = ranked.slice(0, MATRIX.limit), keep = new Set(top);
  const links = linksOf(rows.filter(r => keep.has(r.source) && keep.has(r.target)));
  return {view: 'matrix', ids: matrixOrder(top, links), links, total: ranked.length};
}

function matrixOrder(ids, links) {
  const weight = new Map(ids.map(id => [id, new Map()]));
  for (const l of links) { weight.get(l.a).set(l.b, l.weight); weight.get(l.b).set(l.a, l.weight); }
  const order = [], left = [...ids];
  const pull = id => order.reduce((s, p) => s * MATRIX.decay + (weight.get(id).get(p) || 0), 0);
  while (left.length) {
    const next = left.reduce((best, id) => pull(id) > pull(best) ? id : best);
    order.push(next);
    left.splice(left.indexOf(next), 1);
  }
  return order;
}

const kindLabel = group => REL_GROUPS.find(g => g.key === group).label;
function matrixPair(l, at) {
  const [x, y] = at.get(l.a) < at.get(l.b) ? [l.a, l.b] : [l.b, l.a];
  return `${displayName(D.byId[x])} and ${displayName(D.byId[y])}`;
}
function matrixSays(l, at) {
  const history = tieHistory(l.rows);
  return `${matrixPair(l, at)}, ${kindLabel(l.group)}${l.fresh ? ', new this chapter' : ''}: ${l.rows.map(relText).join('; ')}${history ? `. ${history}` : ''}`;
}
function matrixTip(l, at) {
  const history = tieHistory(l.rows), more = l.rows.length - MATRIX.rows;
  return `<b>${esc(matrixPair(l, at))}</b><div>${swatch(l.group)}${kindLabel(l.group)}${l.fresh ? ' <span class="newtag">new</span>' : ''}</div>`
    + `<ul class="hrels">${l.rows.slice(0, MATRIX.rows).map(r => `<li>${esc(relText(r))}</li>`).join('')}${more > 0 ? `<li class="muted">and ${more} more</li>` : ''}</ul>`
    + (history ? `<div class="muted">${esc(history)}</div>` : '');
}

function matrixName(id) {
  const {died} = fate(id), link = `<a ${goTo('e:' + id)}>${esc(displayName(D.byId[id]))}</a>`;
  return died == null ? link : `<span class="dead" title="Died ch ${died}">${link} <span class="dagger">${DAGGER}</span></span>`;
}

function renderMatrix(m) {
  const n = m.ids.length, at = new Map(m.ids.map((id, i) => [id, i]));
  const head = (axis, id, i) => `<div class="m${axis}${fate(id).fresh ? ' new' : ''}" data-${axis[0]}="${i}" style="grid-${axis === 'row' ? 'row' : 'column'}:${i + 2}">${matrixName(id)}</div>`;
  const cell = (l, r, c) => `<a class="mcell k-${l.group}${l.fresh ? ' new' : ''}" data-r="${r}" data-c="${c}" style="grid-area:${r + 2}/${c + 2};background:var(--r-${l.group})" ${goTo(pairRoute(m.ids[r], m.ids[c]))} tabindex="-1" aria-label="${esc(matrixSays(l, at))}"></a>`;
  const grid = `<i class="mhl" id="mhr"></i><i class="mhl" id="mhc"></i>`
    + m.ids.map((id, i) => `<i class="mdiag" style="grid-area:${i + 2}/${i + 2}"></i>`).join('')
    + m.links.map(l => cell(l, at.get(l.a), at.get(l.b)) + cell(l, at.get(l.b), at.get(l.a))).join('')
    + m.ids.map((id, i) => head('row', id, i) + head('col', id, i)).join('');
  const fresh = freshNote({character: m.ids.filter(id => fate(id).fresh).length, tie: m.links.filter(l => l.fresh).length});
  const subtitle = n ? `${n === m.total ? `All ${n}` : `The ${n} most present of ${m.total}`} characters with a tie by chapter ${S.n}` : `No two characters are tied by chapter ${S.n}`;
  const legend = REL_GROUPS.filter(g => m.links.some(l => l.group === g.key)).map(g => `<span>${swatch(g.key)}${g.label}</span>`).join('')
    + `<span><i class="swatch mnewkey"></i>New this chapter</span><span><span class="dagger">${DAGGER}</span> Died</span>`;
  const body = n ? `<div class="mlegend">${legend}</div><div class="mwrap"><div class="mscroll"><div class="matrix" id="matrix" style="--n:${n}">${grid}</div></div><div class="stip" id="mtip" aria-hidden="true"></div></div>` : '';
  return `<div class="crumbs"><a ${goTo('home')}>Home</a></div><h1>Graph</h1>${graphTabs('matrix')}${fresh}<div class="subtitle">${subtitle}</div>${body}
  <p class="muted glegend">Each row and column is a character, and a filled square means the two are tied by this chapter, coloured by their latest kind of tie. Characters who share ties sit next to each other, so a tight group shows as a block. Hover a square for the ties and how they changed, and select it to see how the two are connected. Select a name to open that character's page.</p>`;
}

function mountMatrix() {
  const m = G.model, grid = $('matrix'), tip = $('mtip');
  if (!grid) return;
  const at = new Map(m.ids.map((id, i) => [id, i])), byPair = new Map(m.links.map(l => [l.key, l]));
  const pair = (r, c) => byPair.get([m.ids[r], m.ids[c]].sort().join('|'));
  const light = (r, c) => {
    grid.querySelectorAll('.on').forEach(el => el.classList.remove('on'));
    grid.classList.toggle('hl', r != null);
    if (r == null) return;
    $('mhr').style.gridArea = `${+r + 2}/1/${+r + 3}/-1`;
    $('mhc').style.gridArea = `1/${+c + 2}/-1/${+c + 3}`;
    grid.querySelector(`.mrow[data-r="${r}"]`).classList.add('on');
    grid.querySelector(`.mcol[data-c="${c}"]`).classList.add('on');
  };
  grid.addEventListener('pointerover', ev => {
    const el = ev.target.closest('[data-r],[data-c]');
    const r = el?.dataset.r ?? el?.dataset.c, c = el?.dataset.c ?? el?.dataset.r;
    light(r, c);
    const l = el?.classList.contains('mcell') && pair(+r, +c);
    if (!l) return tip.classList.remove('show');
    tip.innerHTML = matrixTip(l, at);
    tip.classList.add('show');
    const box = tip.parentElement.getBoundingClientRect(), b = el.getBoundingClientRect();
    tip.style.left = Math.max(8, Math.min(b.right - box.left + 10, box.width - tip.offsetWidth - 8)) + 'px';
    tip.style.top = (b.bottom - box.top + 10) + 'px';
  });
  grid.addEventListener('pointerleave', () => { light(); tip.classList.remove('show'); });
}

const orgTypes = () => new Set(groupTypes(TYPE_GROUPS.find(g => g.key === 'groups')));
const MEMBER_FAMS = new Set(['membership', 'faith', 'service']);
const LEADS = /\b(?:leads?|leader|head|captain|chief|founder|founded|commander|boss|director|president|chairman|king|queen|ruler|cardinal|archbishop|bishop|pope|master)\b/i;
const NOT_NOW = /\b(?:former|formerly|ex|once|previous|suspected|possibly|applicant|candidate|plans|wants|hopes)\b/i;
const leads = role => LEADS.test(role) && !NOT_NOW.test(role);
const FACTION = {rows: 8, also: 3, ties: 6};
const factionRoute = id => 'graph:factions' + (id ? ':' + id : '');
const ladderRoute = id => 'graph:ladder' + (id ? ':' + id : '');
const firstOf = r => Math.min(...r.chapters);
const count = (n, noun) => `${n} ${n === 1 ? noun : plural(noun)}`;

function namedIn(text, names) {
  let rest = text.toLowerCase();
  const found = new Set();
  for (const [name, id] of names.slice().sort((a, b) => b[0].length - a[0].length)) {
    const next = rest.replace(new RegExp(`(?<![\\p{L}\\p{N}])${reEsc(name.toLowerCase())}(?![\\p{L}\\p{N}])`, 'gu'), ' ');
    if (next !== rest) { found.add(id); rest = next; }
  }
  return found;
}
const currentObs = obs => until(obs || []).filter(o => role(o.timeline) === 'current');

function factionsAt(arg) {
  const orgs = orgTypes();
  const isOrg = id => orgs.has(D.byId[id].type);
  const members = new Map();
  const join = (org, id, role, chapter) => {
    const ms = members.get(org) || members.set(org, new Map()).get(org);
    const m = ms.get(id) || ms.set(id, {id, roles: [], chapter}).get(id);
    if (role && !m.roles.includes(role)) m.roles.push(role);
    m.chapter = Math.min(m.chapter, chapter);
  };
  const said = [];
  for (const r of edgesAt()) {
    if (r.role === 'erased' || r.status === 'belief') continue;
    const [a, b] = [isOrg(r.source), isOrg(r.target)];
    if (a && b && sectorFor(r.family) !== 'things') said.push({a: r.source, b: r.target, label: r.label, detail: r.detail, group: groupOf(r.family), chapter: firstOf(r), last: Math.max(...r.chapters)});
    else if (a !== b && MEMBER_FAMS.has(r.family) && isPerson(a ? r.target : r.source)) join(a ? r.source : r.target, a ? r.target : r.source, r.label, firstOf(r));
  }
  const named = D.entities.filter(e => vis(e) && orgs.has(e.type)).flatMap(e => visNames(e).map(n => [n, e.id]));
  for (const e of D.entities) {
    const seen = vis(e) && isPerson(e.id) ? currentObs(e.profile?.fields.affiliation) : [];
    const last = seen.at(-1)?.chapter;
    const orgsIn = seen.map(o => namedIn(o.value, named));
    const since = org => Math.min(...seen.filter((o, i) => orgsIn[i].has(org)).map(o => o.chapter));
    seen.forEach((o, i) => { if (o.chapter === last) for (const org of orgsIn[i]) join(org, e.id, '', since(org)); });
  }
  const memberOf = new Map();
  for (const [org, ms] of members) for (const id of ms.keys()) (memberOf.get(id) || memberOf.set(id, []).get(id)).push(org);
  const groups = [...members].map(([id, ms]) => ({id, members: [...ms.values()].map(m => ({...m, leader: m.roles.some(leads), also: memberOf.get(m.id).filter(o => o !== id).sort(byName)}))
    .sort((x, y) => y.leader - x.leader || x.chapter - y.chapter || byName(x.id, y.id))}))
    .sort((x, y) => y.members.length - x.members.length || byName(x.id, y.id));
  const order = REL_GROUPS.map(g => g.key);
  const pairs = new Map();
  for (const t of said) {
    const key = [t.a, t.b].sort().join('|'), p = pairs.get(key);
    const lead = !p || t.last > p.last || (t.last === p.last && wording(t).length > wording(p).length) ? t : p;
    pairs.set(key, {...lead, chapter: Math.min(t.chapter, p?.chapter ?? t.chapter)});
  }
  const ties = [...pairs.values()];
  ties.sort((x, y) => order.indexOf(x.group) - order.indexOf(y.group) || x.chapter - y.chapter || byName(x.a, y.a));
  const focus = arg && members.has(live(arg)) ? live(arg) : null;
  return {view: 'factions', focus, groups, ties};
}

const groupLink = (id, carded) => carded.has(id) ? `<a ${goTo(factionRoute(id))}>${esc(displayName(D.byId[id]))}</a>` : entLink(id);

function factionCard(g, on, carded) {
  const e = D.byId[g.id];
  const row = m => `<li${m.leader ? ' class="flead"' : ''}>${who(m.id)} <span class="frole">${esc(m.roles.join(', ') || 'affiliated')}</span>${newTag(m.chapter)}`
    + `${m.also.length ? ` <span class="falso">also ${m.also.slice(0, FACTION.also).map(id => groupLink(id, carded)).join(', ')}${m.also.length > FACTION.also ? ` and ${m.also.length - FACTION.also} more` : ''}</span>` : ''}</li>`;
  const rows = g.members.map(row), rest = on ? [] : rows.slice(FACTION.rows);
  const more = rest.length ? expander(`<span class="ifshut">Show all ${rows.length}</span><span class="ifopen">Show fewer</span>`, `<ul class="flist">${rest.join('')}</ul>`).join('') : '';
  return `<section class="fcard${on ? ' on' : ''}" style="--c:${typeColor(e.type)}"><h3><a ${goTo(factionRoute(on ? '' : g.id))} aria-pressed="${on}">${esc(displayName(e))}</a> <small>${g.members.length}</small>${newTag(e.first)}</h3>`
    + `<ul class="flist">${rows.slice(0, on ? rows.length : FACTION.rows).join('')}</ul>${more}<a class="fopen" ${goTo('e:' + g.id)}>Open page</a></section>`;
}

function renderFactions(m) {
  const carded = new Set(m.groups.map(g => g.id));
  const ties = m.focus ? m.ties.filter(t => t.a === m.focus || t.b === m.focus) : m.ties;
  const tie = t => `<li>${swatch(t.group)}${groupLink(t.a, carded)} <span class="rt">${esc(predicate(t.label))}</span> ${groupLink(t.b, carded)}${detailHtml(t, t.last)} <span class="chip">ch ${t.chapter}</span>${newTag(t.chapter)}</li>`;
  const rest = ties.slice(FACTION.ties).map(tie);
  const more = rest.length ? expander(`<span class="ifshut">Show all ${ties.length}</span><span class="ifopen">Show fewer</span>`, `<ul>${rest.join('')}</ul>`).join('') : '';
  const strip = ties.length ? `<div class="fties"><h4>Between groups</h4><ul>${ties.slice(0, FACTION.ties).map(tie).join('')}</ul>${more}</div>` : '';
  const fresh = freshNote({group: m.groups.filter(g => D.byId[g.id].first === S.n).length, member: m.groups.reduce((s, g) => s + g.members.filter(x => x.chapter === S.n).length, 0), tie: m.ties.filter(t => t.chapter === S.n).length});
  const shown = m.focus ? [m.groups.find(g => g.id === m.focus), ...m.groups.filter(g => g.id !== m.focus)] : m.groups;
  const people = new Set(m.groups.flatMap(g => g.members.map(x => x.id))).size;
  const subtitle = m.groups.length ? `${count(m.groups.length, 'group')} with ${count(people, 'known member')} by chapter ${S.n}${m.focus ? `, showing ${entLink(m.focus)} first` : ''}` : `No group has a known member by chapter ${S.n}`;
  return `<div class="crumbs"><a ${goTo('home')}>Home</a></div><h1>Graph</h1>${graphTabs('factions')}${fresh}<div class="subtitle">${subtitle}</div>${strip}
  <div class="fgrid">${shown.map(g => factionCard(g, g.id === m.focus, carded)).join('')}</div>
  <p class="muted glegend">Each card is a group with the people known to belong to it, leaders first, and the role the book gives them. Someone in several groups appears in each, with links to the others. Select a group's name to bring it to the front with all its members and only its ties to other groups.</p>`;
}

const HOLD_FAMS = new Set(['kind', 'ownership', 'membership', 'faith']);
const rankOnly = () => new RegExp(`^${reEsc(D.book.ladder.step_type)}\\s*\\d+$`, 'i');
const stepNames = e => visNames(e).filter(n => !rankOnly().test(n));
const rankLabel = rank => D.book.ladder.rank === 'number' ? `${cap(D.book.ladder.step_type)} ${rank}` : `#${rank}`;

const strongestStage = (text, stages) => {
  const found = namedIn(text, stages.map((t, i) => [t.name, i]));
  return found.size ? stages[Math.max(...found)] : null;
};

function holdersAt(stepOf, power, groupIds, stagesOf) {
  const powerKey = key => [...D.power].some(t => key.toLowerCase().includes(t));
  const names = [...stepOf.keys()].flatMap(id => stepNames(D.byId[id]).map(n => [n, id])).concat(groupIds.flatMap(id => visNames(D.byId[id]).map(n => [n, id])));
  const evidence = [];
  for (const e of D.entities) {
    if (!vis(e) || !isPerson(e.id) || !e.profile) continue;
    for (const [key, obs] of Object.entries(e.profile.fields)) if (powerKey(key)) for (const o of currentObs(obs)) {
      const found = [...namedIn(o.value, names)];
      const groups = found.filter(id => groupIds.includes(id)), steps = found.filter(id => stepOf.has(id));
      const kept = groups.length ? steps.filter(s => groups.includes(stepOf.get(s))) : steps;
      if (kept.length) kept.forEach(s => evidence.push({holder: e.id, group: stepOf.get(s), step: s, chapter: o.chapter, stage: strongestStage(o.value, stagesOf.get(s))}));
      else groups.forEach(g => evidence.push({holder: e.id, group: g, step: null, chapter: o.chapter}));
    }
  }
  for (const r of edgesAt()) {
    if (r.role === 'erased' || r.status !== 'stated' || !HOLD_FAMS.has(r.family)) continue;
    for (const [x, y] of [[r.source, r.target], [r.target, r.source]]) if (isPerson(x) && (stepOf.has(y) || groupIds.includes(y)))
      for (const c of r.chapters) evidence.push({holder: x, group: stepOf.has(y) ? stepOf.get(y) : y, step: stepOf.has(y) ? y : null, chapter: c, stage: null});
  }
  const by = new Map();
  for (const ev of evidence) (by.get(ev.holder) || by.set(ev.holder, []).get(ev.holder)).push(ev);
  const placed = [];
  for (const [holder, evs] of by) {
    const last = Math.max(...evs.map(ev => ev.chapter));
    const now = evs.filter(ev => ev.chapter === last);
    const ranked = now.filter(ev => ev.step);
    const outranked = ev => ranked.some(o => o.group === ev.group && power.get(o.step) > power.get(ev.step));
    const current = new Map((ranked.length ? ranked : now).filter(ev => !ev.step || !outranked(ev)).map(ev => [ev.step || ev.group, ev]));
    const first = new Map();
    for (const ev of evs.filter(ev => ev.step).sort((a, b) => a.chapter - b.chapter)) first.has(ev.step) || first.set(ev.step, ev.chapter);
    for (const [key, cur] of current) {
      const before = Math.max(0, ...evs.filter(ev => (ev.step || ev.group) !== key && ev.chapter < last).map(ev => ev.chapter));
      const since = Math.min(...evs.filter(ev => (ev.step || ev.group) === key && ev.chapter > before).map(ev => ev.chapter));
      const sameLadder = cur.step ? [...first].filter(([step]) => !current.has(step) && stepOf.get(step) === cur.group).map(([step, chapter]) => ({step, chapter})) : [];
      const passed = sameLadder.filter(x => power.get(x.step) < power.get(cur.step)).sort((a, b) => power.get(a.step) - power.get(b.step));
      const staged = evs.filter(ev => ev.step === cur.step && ev.stage).sort((a, b) => a.chapter - b.chapter);
      const stage = staged.at(-1)?.stage || null;
      const stages = stagesOf.get(cur.step) || [];
      const rose = staged.filter(ev => stages.indexOf(ev.stage) < stages.indexOf(stage)).map(ev => ({stage: ev.stage, chapter: ev.chapter}));
      const reached = stage ? Math.min(...staged.filter(ev => ev.stage === stage).map(ev => ev.chapter)) : since;
      placed.push({holder, group: cur.group, step: cur.step, since: reached, passed, earlier: sameLadder.filter(x => !passed.includes(x)), stage, rose: rose.slice(-1)});
    }
  }
  return placed.sort((a, b) => a.since - b.since || byName(a.holder, b.holder));
}

function ladderAt(arg) {
  const spec = D.book.ladder;
  if (!spec) return {view: 'ladder', focus: null, ladders: []};
  const strength = rank => spec.direction === 'descending' ? -rank : rank;
  const weakFirst = (a, b) => strength(a) - strength(b);
  const known = visLadders().map(l => ({group: live(l.group), steps: ladderSteps(l).map(s => ({...s, id: live(s.id), stages: until(s.stages || [])}))}));
  const stepOf = new Map(known.flatMap(l => l.steps.map(s => [s.id, l.group])));
  const power = new Map(known.flatMap(l => l.steps.map(s => [s.id, strength(s.rank)])));
  const stagesOf = new Map(known.flatMap(l => l.steps.map(s => [s.id, s.stages])));
  const placed = holdersAt(stepOf, power, known.map(l => l.group).filter(Boolean), stagesOf);
  const ladders = known.map(l => ({group: l.group, unranked: placed.filter(p => p.group === l.group && !p.step),
    rungs: [...new Set(l.steps.map(s => s.rank))].sort(weakFirst).map(rank => ({rank,
      steps: l.steps.filter(s => s.rank === rank).map(s => ({id: s.id, chapter: s.chapter, stages: s.stages, holders: placed.filter(p => p.step === s.id),
        passed: placed.flatMap(p => p.passed.some(x => x.step === s.id) ? [{holder: p.holder, now: p.step, chapter: p.since}] : [])}))}))}));
  const focus = arg && ladders.some(l => l.group === live(arg)) ? live(arg) : null;
  return {view: 'ladder', focus, ladders};
}

const stageList = stages => stages.length ? `<ol class="lstages">${stages.map(t => `<li>${esc(t.name)}${newTag(t.chapter)}</li>`).join('')}</ol>` : '';

function stepBlock(s) {
  const e = D.byId[s.id], main = displayName(e);
  const aka = stepNames(e).filter(n => n !== main);
  const l = lede(e);
  const kin = new Map();
  for (const r of visRels(s.id)) {
    const other = r.source === s.id ? r.target : r.source, t = D.byId[other].type;
    if (D.power.has(t) && t !== D.book.ladder.step_type && t !== D.book.ladder.group_type) (kin.get(t) || kin.set(t, new Set()).get(t)).add(other);
  }
  const powers = [...kin].map(([t, ids]) => `<div class="lpow">${esc(catName(t))}: ${[...ids].sort(byName).map(entLink).join(', ')}</div>`).join('');
  const was = x => `${esc(displayName(D.byId[x.step]))} (ch ${x.chapter})`;
  const history = h => [h.passed.length ? `advanced from ${was(h.passed.at(-1))}` : '', h.earlier.length ? `earlier ${h.earlier.map(was).join(', ')}` : '',
    ...h.rose.map(x => `rose from ${esc(x.stage.name)} (ch ${x.chapter})`)].filter(Boolean).map(t => ` <span class="lprev">${t}</span>`).join('');
  const rows = s.holders.map(h => `<li>${who(h.holder)}${h.stage ? ` <span class="chip">${esc(h.stage.name)}</span>` : ''} <span class="chip">since ch ${h.since}</span>${newTag(h.since)}${history(h)}</li>`)
    .concat(s.passed.map(h => `<li class="lpast">${who(h.holder)} <span class="lprev">now ${esc(displayName(D.byId[h.now]))}, ch ${h.chapter}</span></li>`));
  const holders = rows.length ? `<ul class="lholders">${rows.join('')}</ul>` : '';
  return `<div class="lstep"><div class="lname">${entLink(s.id)}${aka.length ? ` <span class="laka">also ${aka.map(esc).join(', ')}</span>` : ''} ${chLink(s.chapter)}${newTag(s.chapter)}</div>`
    + `${l.text ? `<p class="lsum">${linkify(l.text, s.id, l.chapter)}</p>` : ''}${stageList(s.stages)}${powers}${holders}</div>`;
}

const LADDER_SHAPES = {
  grouped: {
    head: (l, on) => `<a ${goTo(ladderRoute(on ? '' : l.group))} aria-pressed="${on}">${esc(displayName(D.byId[l.group]))}</a>`,
    color: l => typeColor(D.byId[l.group].type),
    foot: l => `<a class="fopen" ${goTo('e:' + l.group)}>Open page</a>`,
    subtitle: (spec, m) => m.ladders.length ? `${count(m.ladders.length, spec.group_type)} known by chapter ${S.n}, each from its weakest ${spec.step_type} to its strongest` : `No ${spec.group_type} has a known ${spec.step_type} by chapter ${S.n}.`,
    legend: spec => `Each ${esc(spec.group_type)} runs from its weakest ${esc(spec.step_type)} at the top to its strongest known at the bottom. A ${esc(spec.step_type)} shows once the book places it, with what is known of it so far and who holds it. Someone who moves up keeps the powers of the ${esc(plural(spec.step_type))} below, so they stay listed there, fainter, with where they are now.`,
  },
  shared: {
    head: () => esc(cap(plural(D.book.ladder.step_type))),
    color: () => typeColor(D.book.ladder.step_type),
    foot: () => '',
    subtitle: (spec, m) => m.ladders.length ? `One ladder of ${plural(spec.step_type)} that everyone climbs: ${count(m.ladders[0].rungs.length, spec.step_type)} known by chapter ${S.n}, from the weakest to the strongest` : `No ${spec.step_type} is placed on the ladder by chapter ${S.n}.`,
    legend: spec => `The ladder runs from the weakest ${esc(spec.step_type)} at the top to the strongest known at the bottom. Each ${esc(spec.step_type)} lists its sub-stages in order, weakest first, as the book names them. Each holder shows at the ${esc(spec.step_type)} and sub-stage the book last gives them. Someone who moves up stays listed at the ${esc(plural(spec.step_type))} below, fainter, with where they are now.`,
  },
};
const ladderShape = () => LADDER_SHAPES[D.book.ladder.shape || 'grouped'];

function ladderCard(l, on) {
  const spec = D.book.ladder, shape = ladderShape();
  const rows = [];
  l.rungs.forEach((r, i) => {
    const gap = spec.rank === 'number' && i ? Math.abs(r.rank - l.rungs[i - 1].rank) - 1 : 0;
    if (gap > 0) rows.push(`<li class="lgap">${gap === 1 ? 'One rank' : `${gap} ranks`} not yet known</li>`);
    rows.push(`<li class="lrung"><span class="lrank">${esc(rankLabel(r.rank))}</span><div class="lsteps">${r.steps.map(stepBlock).join('')}</div></li>`);
  });
  const unranked = l.unranked.length ? `<p class="lunknown">On this ${esc(spec.group_type)}, rank not yet known: ${l.unranked.map(p => who(p.holder)).join(', ')}</p>` : '';
  const holders = new Set([...l.rungs.flatMap(r => r.steps.flatMap(x => x.holders)), ...l.unranked].map(p => p.holder)).size;
  return `<section class="lcard${on ? ' on' : ''}" style="--c:${shape.color(l)}"><h3>${shape.head(l, on)} <small>${count(l.rungs.length, 'rank')} known${holders ? `, ${count(holders, 'holder')}` : ''}</small></h3>`
    + `<div class="lend">Weakest</div><ol class="lrungs">${rows.join('')}</ol><div class="lend">Strongest known</div>${unranked}${shape.foot(l)}</section>`;
}

function renderLadder(m) {
  const spec = D.book.ladder;
  const shown = m.focus ? [m.ladders.find(l => l.group === m.focus), ...m.ladders.filter(l => l.group !== m.focus)] : m.ladders;
  const steps = m.ladders.flatMap(l => l.rungs.flatMap(r => r.steps));
  const fresh = freshNote({step: steps.filter(s => s.chapter === S.n).length, holder: steps.reduce((n, s) => n + s.holders.filter(h => h.since === S.n).length, 0)});
  const subtitle = !spec ? 'This book has no power ladder.' : ladderShape().subtitle(spec, m);
  return `<div class="crumbs"><a ${goTo('home')}>Home</a></div><h1>Graph</h1>${graphTabs('ladder')}${fresh}<div class="subtitle">${esc(subtitle)}</div>
  <div class="lgrid">${shown.map(l => ladderCard(l, l.group === m.focus)).join('')}</div>
  ${m.ladders.length ? `<p class="muted glegend">${ladderShape().legend(spec)}</p>` : ''}`;
}

const KIN = [
  {re: /\b(?:grand|great)[\w-]*\s?(?:father|mother|parent|dad|mum|mom)s?\b/, role: 'kin', gen: 2},
  {re: /\b(?:grand|great)[\w-]*\s?(?:son|daughter|child|children)\b/, role: 'kin', gen: -2},
  {re: /\b(?:step|foster|adoptive )?(?:father|mother|parent|dad|mum|mom)s?\b/, role: 'parent', gen: 1},
  {re: /\b(?:step|foster|adoptive )?(?:son|daughter|child|children)s?\b/, role: 'child', gen: -1},
  {re: /\b(?:(?:half|step)-?)?(?:brother|sister|sibling|twin)s?\b/, role: 'sibling', gen: 0},
  {re: /\b(?:husband|wife|spouse|married|widow|widower)\b/, role: 'spouse', gen: 0},
  {re: /\b(?:uncle|aunt)s?\b/, role: 'kin', gen: 1},
  {re: /\b(?:nephew|niece)s?\b/, role: 'kin', gen: -1},
  {re: /\bcousins?\b/, role: 'kin', gen: 0},
];
const KIN_OTHER = /\b(?:relatives?|related|kin|kinsman|kinswoman|descendant|ancestor|in-laws?)\b/;
const NOT_KIN = /\b(?:figure|like)\b/;
const KIN_RANK = {parent: 3, spouse: 2, sibling: 1, kin: 0};
const UNSURE = /\b(?:possibly|probably|presumably|perhaps|maybe|suspected|alleged|rumou?red|supposed|claimed|believed)\b/i;
const FAMILY = {cards: 6, w: 136, h: 40, gapX: 22, gapY: 58, pad: 16, chars: 18, line: 15};

const otherEnd = (t, id) => t.a === id ? t.b : t.a;

function kinOf(r) {
  if (r.family !== 'kin' && r.family !== 'romance') return null;
  const w = wordKey(r.label), k = KIN.find(row => row.re.test(w));
  if (NOT_KIN.test(w)) return null;
  if (!k) return r.family === 'kin' && KIN_OTHER.test(w) ? {role: 'kin', gen: null} : null;
  if (r.family === 'romance' && k.role !== 'spouse') return null;
  return /\bin[- ]law\b/.test(w) ? {role: 'kin', gen: k.gen} : k;
}

function familyAt() {
  const pairs = new Map();
  for (const r of edgesAt()) {
    if (r.role === 'erased' || !isPerson(r.source) || !isPerson(r.target)) continue;
    const k = kinOf(r);
    if (!k) continue;
    const [a, b, role, gen] = k.role === 'child' ? [r.target, r.source, 'parent', 1] : [r.source, r.target, k.role, k.gen];
    const key = [a, b].sort().join('|');
    const t = pairs.get(key) || pairs.set(key, {key, a, b, role, gen, rows: []}).get(key);
    if (KIN_RANK[role] > KIN_RANK[t.role] || (role === t.role && t.gen == null && gen != null)) Object.assign(t, {a, b, role, gen});
    t.rows.push(r);
  }
  const ties = [...pairs.values()].map(t => ({...t, implied: t.rows.every(r => r.status !== 'stated' || UNSURE.test(r.label)), chapter: Math.min(...t.rows.map(firstOf))}));
  const adj = new Map();
  for (const t of ties) for (const id of [t.a, t.b]) (adj.get(id) || adj.set(id, []).get(id)).push(t);
  const seen = new Set(), families = [];
  for (const id of [...adj.keys()].sort(byName)) {
    if (seen.has(id)) continue;
    const members = [id];
    seen.add(id);
    for (let i = 0; i < members.length; i++) for (const t of adj.get(members[i])) {
      const o = otherEnd(t, members[i]);
      if (!seen.has(o)) { seen.add(o); members.push(o); }
    }
    if (members.length > 1) families.push(familyLayout(members, ties.filter(t => members.includes(t.a)), adj));
  }
  families.sort((x, y) => y.members.length - x.members.length || x.chapter - y.chapter || byName(x.head, y.head));
  return {view: 'family', families};
}

function generations(members, adj) {
  const head = members.slice().sort((a, b) => adj.get(b).length - adj.get(a).length || byName(a, b))[0];
  const age = new Map([[head, 0]]);
  for (;;) {
    for (let grew = true; grew;) {
      grew = false;
      for (const id of [...age.keys()]) for (const t of adj.get(id)) {
        if (age.has(otherEnd(t, id)) || t.gen == null) continue;
        age.set(otherEnd(t, id), age.get(id) + (t.a === id ? -t.gen : t.gen));
        grew = true;
      }
    }
    const loose = members.find(id => !age.has(id) && adj.get(id).some(t => age.has(otherEnd(t, id))));
    if (!loose) break;
    age.set(loose, age.get(otherEnd(adj.get(loose).find(t => age.has(otherEnd(t, loose))), loose)));
  }
  const top = Math.max(...age.values());
  return {head, row: new Map([...age].map(([id, a]) => [id, top - a]))};
}

function familyLayout(members, ties, adj) {
  const {head, row} = generations(members, adj);
  const rows = Array.from({length: Math.max(...row.values()) + 1}, () => []);
  for (const id of members) rows[row.get(id)].push(id);
  const parents = new Map(), spouse = new Map(), sib = new Map(members.map(id => [id, id]));
  const set = id => sib.get(id) === id ? id : set(sib.get(id));
  for (const t of ties) {
    if (t.role === 'parent') (parents.get(t.b) || parents.set(t.b, []).get(t.b)).push(t.a);
    if (t.role === 'spouse') { spouse.set(t.a, t.b); spouse.set(t.b, t.a); }
    if (t.role === 'sibling') sib.set(set(t.a), set(t.b));
  }
  const x = new Map();
  const mean = ids => ids.length ? ids.reduce((s, id) => s + x.get(id), 0) / ids.length : null;
  rows.forEach(ids => {
    const want = new Map(ids.map(id => {
      const ps = (parents.get(id) || []).filter(p => x.has(p));
      return [id, mean(ps.length ? ps : adj.get(id).map(t => otherEnd(t, id)).filter(o => x.has(o)))];
    }));
    for (const id of ids) if (want.get(id) == null) {
      const mate = ids.find(o => o !== id && want.get(o) != null && (set(o) === set(id) || spouse.get(id) === o));
      if (mate) want.set(id, want.get(mate));
    }
    const order = ids.slice().sort((p, q) => (want.get(p) ?? 1e9) - (want.get(q) ?? 1e9) || cmp(set(p), set(q)) || byName(p, q));
    for (const id of order.slice()) {
      const s = spouse.get(id);
      if (!order.includes(s) || Math.abs(order.indexOf(s) - order.indexOf(id)) === 1) continue;
      const mover = (parents.get(s) || []).length <= (parents.get(id) || []).length ? s : id, stay = mover === s ? id : s;
      order.splice(order.indexOf(mover), 1);
      order.splice(order.indexOf(stay) + 1, 0, mover);
    }
    const xs = [];
    order.forEach((id, k) => xs.push(k ? Math.max(want.get(id) ?? -Infinity, xs[k - 1] + 1) : want.get(id) ?? 0));
    const pulls = order.map((id, k) => want.get(id) == null ? null : want.get(id) - xs[k]).filter(d => d != null);
    const off = pulls.length ? pulls.reduce((s, d) => s + d, 0) / pulls.length : 0;
    order.forEach((id, k) => x.set(id, xs[k] + off));
    ids.splice(0, ids.length, ...order);
  });
  const left = Math.min(...x.values());
  return {head, rows, ties, chapter: Math.min(...ties.map(t => t.chapter)),
    members: members.map(id => ({id, row: row.get(id), x: num(x.get(id) - left), ...fate(id)})).sort((a, b) => a.row - b.row || a.x - b.x)};
}

function familyName(f) {
  const last = new Map();
  for (const m of f.members) {
    const words = displayName(D.byId[m.id]).split(/\s+/);
    if (words.length > 1 && /^\p{Lu}/u.test(words.at(-1))) last.set(words.at(-1), (last.get(words.at(-1)) || 0) + 1);
  }
  const [name, n] = [...last].sort((a, b) => b[1] - a[1])[0] || [];
  return n >= 2 ? `${name} family` : `${displayName(D.byId[f.head])}'s family`;
}

function familySvg(f) {
  const {w, h, gapX, gapY, pad, line} = FAMILY;
  const at = new Map(f.members.map(m => [m.id, {x: num(m.x * (w + gapX)), y: m.row * (h + gapY)}]));
  const parents = id => f.ties.filter(t => t.role === 'parent' && t.b === id).map(t => t.a);
  const wed = (p, q) => f.ties.some(t => t.role === 'spouse' && [t.a, t.b].includes(p) && [t.a, t.b].includes(q));
  const tie = t => {
    const a = at.get(t.a), b = at.get(t.b);
    let d;
    if (t.role === 'parent') {
      const mate = parents(t.b).find(p => p !== t.a && wed(p, t.a) && at.get(p).y === a.y);
      const from = mate ? [num((a.x + at.get(mate).x) / 2 + w / 2), a.y + h / 2] : [num(a.x + w / 2), a.y + h];
      d = `M${from[0]} ${from[1]}V${b.y - gapY / 2}H${num(b.x + w / 2)}V${b.y}`;
    } else if (t.role === 'spouse' && a.y === b.y && Math.abs(Math.abs(a.x - b.x) - (w + gapX)) < 1) {
      d = `M${num(Math.min(a.x, b.x) + w)} ${a.y + h / 2}H${num(Math.max(a.x, b.x))}`;
    } else if (t.role === 'sibling' && a.y === b.y) {
      if (parents(t.a).some(p => parents(t.b).includes(p))) return '';
      d = `M${num(a.x + w / 2)} ${a.y}V${a.y - 10}H${num(b.x + w / 2)}V${b.y}`;
    } else {
      d = curve([a.x + w / 2, a.y + (a.y === b.y ? 0 : h / 2)], [b.x + w / 2, b.y + (a.y === b.y ? 0 : h / 2)], a.y === b.y ? (a.x < b.x ? -0.25 : 0.25) : 0.15);
    }
    return `<path class="ftie ${t.role}${t.implied ? ' implied' : ''}${t.chapter === S.n ? ' new' : ''}" d="${d}"><title>${esc(t.rows.map(relText).join('; '))}</title></path>`;
  };
  const node = m => {
    const {x, y} = at.get(m.id), name = displayName(D.byId[m.id]), {lines} = wrapName(name, FAMILY.chars);
    const top = y + h / 2 + 4 - (lines.length - 1) * line / 2;
    const text = lines.map((t, i) => `<tspan x="${num(x + w / 2)}" y="${num(top + i * line)}">${esc(t)}${m.died != null && i === lines.length - 1 ? `<tspan class="dagger"> ${DAGGER}</tspan>` : ''}</tspan>`).join('');
    return `<a class="ent fnode${m.died != null ? ' dead' : ''}${m.fresh ? ' new' : ''}" data-ent="${m.id}" href="#${hashFor({p: 'e:' + m.id, tab: ''})}" aria-label="${esc(name + nodeSays(m))}">`
      + `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="6"/><text>${text}</text></a>`;
  };
  const W = num(Math.max(...f.members.map(m => at.get(m.id).x)) + w + 2 * pad), H = f.rows.length * (h + gapY) - gapY + 2 * pad;
  return `<svg class="family" viewBox="${-pad} ${-pad} ${W} ${H}" width="${W}" height="${H}" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="${esc(familyName(f))}">`
    + `<g class="fties">${f.ties.map(tie).join('')}</g><g class="fnodes">${f.members.map(node).join('')}</g></svg>`;
}

const people = n => `${n} ${n === 1 ? 'person' : 'people'}`;

const WEARS = /^(?:disguised? as|impersonat\w*|posed as|posing as|masquerad\w* as)\b/i;

function masksAt() {
  const by = new Map();
  for (const r of edgesAt()) {
    if (r.role === 'erased' || r.status === 'belief' || !WEARS.test(r.label) || !isPerson(r.source)) continue;
    const faces = by.get(r.source) || by.set(r.source, new Map()).get(r.source);
    const face = faces.get(r.target) || faces.set(r.target, {id: r.target, chapters: [], quotes: []}).get(r.target);
    face.chapters.push(...r.chapters);
    face.quotes.push(...r.quotes.filter(q => !face.quotes.includes(q)));
  }
  const wearers = [...by].map(([id, faces]) => ({id,
    faces: [...faces.values()].map(f => ({...f, first: Math.min(...f.chapters), last: Math.max(...f.chapters)})).sort((a, b) => a.first - b.first),
    names: (D.parts[id] || []).map(p => D.byId[p]).filter(p => p.type === 'character' && p.merged.chapter <= S.n && p.first <= S.n).sort((a, b) => a.first - b.first)}));
  return {view: 'masks', wearers: wearers.sort((a, b) => b.faces.length - a.faces.length || byName(a.id, b.id))};
}

function renderMasks(m) {
  const span = f => f.first === f.last ? chLink(f.first) : `${chLink(f.first)} to ${chLink(f.last)}`;
  const face = f => `<li class="hop">${entLink(f.id)} <span class="csince">${span(f)}</span>${quotes(f.quotes.slice(0, 1))}</li>`;
  const cards = m.wearers.map(w => `<section class="famcard"><h3>${entLink(w.id)} <small>${count(w.faces.length, 'face')}</small></h3>${w.names.length ? `<p class="muted">Also goes by ${w.names.map(p => `${esc(displayName(p))} (${chLink(p.first)})`).join(', ')}</p>` : ''}<ol class="hops">${w.faces.map(face).join('')}</ol></section>`);
  return `<div class="crumbs"><a ${goTo('home')}>Home</a></div><h1>Graph</h1>${graphTabs('masks')}<div class="subtitle">${count(m.wearers.length, 'character')} seen wearing someone else's face by chapter ${S.n}</div><div class="famlist">${cards.join('')}</div>`;
}

function renderFamily(m) {
  const cards = m.families.map(f => `<section class="famcard"><h3>${esc(familyName(f))} <small>${people(f.members.length)}</small>${newTag(f.chapter)}</h3><div class="fscroll">${familySvg(f)}</div></section>`);
  const rest = cards.slice(FAMILY.cards);
  const more = rest.length ? expander(`<span class="ifshut">Show all ${cards.length} families</span><span class="ifopen">Show fewer</span>`, rest.join('')).join('') : '';
  const fresh = freshNote({'family tie': m.families.reduce((s, f) => s + f.ties.filter(t => t.chapter === S.n).length, 0)});
  const total = m.families.reduce((s, f) => s + f.members.length, 0);
  const subtitle = m.families.length ? `${count(m.families.length, 'family')} with ${people(total)} tied by blood or marriage by chapter ${S.n}` : `No family ties are known by chapter ${S.n}`;
  return `<div class="crumbs"><a ${goTo('home')}>Home</a></div><h1>Graph</h1>${graphTabs('family')}${fresh}<div class="subtitle">${subtitle}</div>
  <div class="famlist">${cards.slice(0, FAMILY.cards).join('')}${more}</div>
  <p class="muted glegend">Each tree is one family as of this chapter, the eldest generation at the top. Lines run down from parents to their children, a thick line joins a married couple, and a bracket joins siblings whose parents are not known. Dashed lines are other kin, or ties the book only implies. A faded name with ${DAGGER} has died. Hover a line for the exact relation, and select a name to open its page.</p>`;
}

const CONTAINS = /^(?:(?:is|was|are|were) )?(?:(?:located|situated|set|built|found|lies|lying|sits|nestled|stands|based) )?(?:in|inside|within|on|at)(?: the)?$|^(?:(?:a|an|the) )?(?:part|district|borough|suburb|quarter|region|province|county|area|ward|neighbou?rhood|street|road|avenue|town|city|village|island|precinct|section|wing|floor|room|building|capital) (?:of|in|within)$/;
const DWELLS = /\b(?:lives?|lived|living|resid\w*|dwell\w*|stays?|stayed|staying|lodg\w*|tenants?|rents?|rented|boards?|home|works?|worked|working|employed|employee|stationed|posted|staff|clerk|runs|manages|managed|proprietor|landlord|landlady|owner|owns|teaches|lectur\w*|professor|stud(?:y|ies|ied|ying|ent|ents)|pupil|enrolled|attends?|attended|graduated?|alumn\w*)\b/;
const PLACES = {open: 2, rows: 8};
const showAll = (n, noun) => n === 1 ? `Show the ${noun}` : `Show all ${n} ${plural(noun)}`;

function placesAt() {
  const kinds = new Set(groupTypes(TYPE_GROUPS.find(g => g.key === 'places')));
  const isPlace = id => kinds.has(D.byId[id].type);
  const rows = edgesAt().filter(r => r.role !== 'erased' && r.status !== 'belief');
  const parent = new Map(), within = new Map(), dwell = new Map();
  const above = id => { const out = []; for (let p = parent.get(id); p && !out.includes(p); p = parent.get(p)) out.push(p); return out; };
  for (const r of rows.slice().sort((a, b) => firstOf(a) - firstOf(b))) {
    if (isPlace(r.source) && isPlace(r.target) && CONTAINS.test(wordKey(r.label))) {
      const cs = within.get(r.source) || within.set(r.source, []).get(r.source);
      if (!cs.includes(r.target)) cs.push(r.target);
    } else if (isPerson(r.source) && isPlace(r.target) && DWELLS.test(wordKey(r.label))) {
      const mine = dwell.get(r.source) || dwell.set(r.source, new Map()).get(r.source);
      (mine.get(r.target) || mine.set(r.target, []).get(r.target)).push(r);
    }
  }
  for (let pass = 0, changed = true; changed && pass <= within.size; pass++) {
    changed = false;
    for (const [id, cs] of within) {
      const ok = cs.filter(c => c !== id && !above(c).includes(id));
      const depth = c => above(c).filter(a => ok.includes(a)).length;
      const best = ok.reduce((b, c) => depth(c) > depth(b) ? c : b, ok[0]);
      if (best && parent.get(id) !== best) { parent.set(id, best); changed = true; }
    }
  }
  const residents = new Map();
  for (const [id, mine] of dwell) for (const [at, rs] of mine) {
    if ([...mine.keys()].some(o => o !== at && above(o).includes(at))) continue;
    (residents.get(at) || residents.set(at, []).get(at)).push({id, rows: rs, chapter: Math.min(...rs.map(firstOf))});
  }
  const kids = new Map();
  for (const [id, p] of parent) (kids.get(p) || kids.set(p, []).get(p)).push(id);
  const order = (a, b) => b.people.length - a.people.length || byName(a.id, b.id);
  const node = (id, depth) => {
    const children = (kids.get(id) || []).map(c => node(c, depth + 1)).sort(order);
    const here = (residents.get(id) || []).sort((a, b) => a.chapter - b.chapter || byName(a.id, b.id));
    return {id, depth, residents: here, children, people: [...new Set([...here.map(x => x.id), ...children.flatMap(c => c.people)])]};
  };
  const roots = [...new Set([...kids.keys(), ...residents.keys()])].filter(id => !parent.has(id)).map(id => node(id, 0)).sort(order);
  return {view: 'places', roots};
}

function placeNode(p) {
  const list = (items, noun, cls) => !items.length ? '' : `<ul class="${cls}">${items.slice(0, PLACES.rows).join('')}</ul>`
    + (items.length > PLACES.rows ? expander(`<span class="ifshut">Show all ${items.length} ${noun}</span><span class="ifopen">Show fewer</span>`, `<ul class="${cls}">${items.slice(PLACES.rows).join('')}</ul>`).join('') : '');
  const role = rows => {
    const r = rows.reduce((a, b) => Math.max(...b.chapters) >= Math.max(...a.chapters) ? b : a);
    const place = displayName(D.byId[p.id]);
    const all = [...new Set(rows.map(x => `${predicate(x.label)} ${place}${x.detail ? ' ' + x.detail : ''}`))];
    return `<span class="prole"${all.length > 1 ? ` title="${esc(all.join('\n'))}"` : ''}>${esc(predicate(r.label))} ${esc(place)}${detailHtml(r, Math.max(...r.chapters))}</span>`;
  };
  const residents = p.residents.map(x => `<li>${who(x.id)} ${role(x.rows)}${newTag(x.chapter)}</li>`);
  const children = p.children.map(placeNode);
  const inside = p.depth >= PLACES.open && children.length
    ? expander(`<span class="ifshut">${showAll(children.length, 'place')} inside</span><span class="ifopen">Hide ${children.length === 1 ? 'it' : 'them'}</span>`, `<ul class="ptree">${children.join('')}</ul>`).join('')
    : list(children, 'places', 'ptree');
  return `<li class="pnode"><div class="phead">${entLink(p.id)}${p.people.length ? ` <small>${people(p.people.length)}</small>` : ''}${newTag(D.byId[p.id].first)}</div>${list(residents, 'people', 'pres')}${inside}</li>`;
}

function renderPlaces(m) {
  const all = new Set(m.roots.flatMap(p => p.people));
  const known = m.roots.filter(p => p.people.length), empty = m.roots.filter(p => !p.people.length);
  const walk = p => [p, ...p.children.flatMap(walk)];
  const nodes = m.roots.flatMap(walk);
  const fresh = freshNote({resident: nodes.reduce((s, p) => s + p.residents.filter(x => x.chapter === S.n).length, 0)});
  const subtitle = nodes.length ? `${people(all.size)} in ${count(nodes.length, 'place')} by chapter ${S.n}` : `No place has a known resident by chapter ${S.n}`;
  return `<div class="crumbs"><a ${goTo('home')}>Home</a></div><h1>Graph</h1>${graphTabs('places')}${fresh}<div class="subtitle">${subtitle}</div>
  <div class="places"><ul class="ptree">${known.map(placeNode).join('')}</ul>${empty.length ? expander(`<span class="ifshut">${showAll(empty.length, 'place')} where no one is known to be</span><span class="ifopen">Hide ${empty.length === 1 ? 'it' : 'them'}</span>`, `<ul class="ptree">${empty.map(placeNode).join('')}</ul>`).join('') : ''}</div>
  <p class="muted glegend">Places nest inside the places the book says they lie in. Each person who lives, works or studies somewhere is listed under the most specific place known, with the book's words for the tie, and a place's count includes everyone in the places inside it.</p>`;
}

function render() {
  $('n').value = S.n;
  $('nlab').textContent = S.n;
  $('ctitle').textContent = ctitle(S.n);
  const vol = volumeAt(S.n), vb = $('vol');
  vb.hidden = !vol;
  if (vol) {
    vb.textContent = vol.label;
    vb.classList.toggle('end', vol.end);
    vb.title = vol.end ? 'Everything up to the end of this volume is shown' : 'Jump to the end of this volume';
  }
  $('brand').href = '#' + hashFor({p: 'home', tab: '', m: ''});
  const c = counts();
  renderSide(c);
  const [kind, arg] = S.p.split(/:(.*)/s);
  const pages = {
    e: () => renderEntity(arg), cat: () => renderCat(D.book.added?.[arg] > S.n ? D.parents[arg] : arg), mysteries: renderMysteries, chapters: renderChapters,
    ch: () => renderChapter(arg), v: () => renderVolume(arg), graph: () => renderGraph(arg), checks: renderChecks,
  };
  const old = $('graph-view');
  $('main').innerHTML = (pages[kind] || (() => renderHome(c)))();
  if (G.full && !(kind === 'graph' && NETWORK_VIEWS.has(G.model.view))) setFull(false);
  if (kind === 'graph') mountGraph(old);
  else Object.assign(G, {shown: null, cam: null});
  document.body.classList.remove('menu-open');
  hideHover();
}

const hover = $('hover');
function showHover(el) {
  const e = D.byId[el.dataset.ent];
  if (!vis(e)) return;
  const l = lede(e), al = visAliases(e).filter(a => a !== displayName(e));
  const said = el.dataset.rels ? el.dataset.rels.split('\n') : [];
  const rels = said.length ? `<ul class="hrels">${said.slice(0, 4).map(t => `<li>${esc(t)}</li>`).join('')}${said.length > 4 ? `<li class="muted">and ${said.length - 4} more</li>` : ''}</ul>` : '';
  hover.innerHTML = `<h4>${esc(displayName(e))}</h4><div class="muted">${esc(cap(e.type))} &middot; since ch ${e.first} &middot; ${visFacts(e.id).length} facts</div>${al.length ? `<div class="muted">aka ${al.map(esc).join(', ')}</div>` : ''}${rels}<p>${esc(rels ? clip(l.text, 220) : l.text)}</p>`;
  const r = (el.querySelector('circle') || el).getBoundingClientRect();
  const w = hover.offsetWidth || 320;
  hover.style.left = Math.max(8, Math.min(scrollX + r.left, scrollX + innerWidth - w - 8)) + 'px';
  hover.style.top = (scrollY + r.bottom + 6) + 'px';
  hover.classList.add('show');
}
function hideHover() { hover.classList.remove('show'); }

function volumeAt(n) {
  const v = D.volumes.find(x => x.from <= n && n <= x.to);
  if (!v) return null;
  const end = n === v.to;
  return {id: v.id, to: v.to, end, label: end ? `End of ${v.name}` : `${v.name} \u00b7 ${n - v.from + 1} of ${v.to - v.from + 1}`};
}

function volumeTicks() {
  const list = document.createElement('datalist');
  list.id = 'volticks';
  list.innerHTML = D.volumes.map(v => `<option value="${v.to}" label="${esc(v.name)}"></option>`).join('');
  document.body.appendChild(list);
  $('n').setAttribute('list', 'volticks');
}

const NOTES = {count: 0, answered: new Set(), pending: null};
const CHECK_KINDS = {shared_name: 'Names two pages both claim', dead_alive: 'Dead, then alive with no explanation',
  description_title: 'Important pages still titled by a description', many_names: 'Pages holding many names', merge: 'Merges the judge was unsure of'};
const openChecks = () => (D.checks || []).filter(c => c.chapter <= S.n && vis(D.byId[c.entity]) && !NOTES.answered.has(c.id));
function renderChecks() {
  const rows = openChecks();
  const answered = (D.checks || []).filter(c => NOTES.answered.has(c.id)).length;
  const groups = Object.keys(CHECK_KINDS).map(k => [k, rows.filter(c => c.kind === k)]).filter(([, g]) => g.length);
  const row = c => `<li class="checkrow"><div>${entLink(c.entity)} <span class="muted">${esc(c.reason)}</span> ${chLink(c.chapter)}</div>
    <div class="checkbtns"><button data-check-right="${c.id}">Looks right</button><button data-check-wrong="${c.id}">Wrong</button></div></li>`;
  return `<h1>Needs checking</h1><div class="subtitle">Pages the build is least sure of, up to chapter ${S.n}. Answer one and it leaves this list; your answer is saved with your notes.${answered ? ` ${answered} answered so far.` : ''}</div>`
    + (NOTES.on ? '' : '<div class="note">Start the wiki with <code>annalist serve</code> to save answers.</div>')
    + (groups.length ? groups.map(([k, g]) => `<h2>${esc(CHECK_KINDS[k])} <span class="muted">(${g.length})</span></h2><ul class="list checks">${g.map(row).join('')}</ul>`).join('')
      : '<p class="muted">Nothing left to check up to this chapter.</p>');
}
async function answerCheck(id, verdict, text) {
  const c = D.checks.find(x => x.id === id), e = D.byId[c.entity];
  const r = await fetch('api/notes', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({page: 'e:' + c.entity, title: displayName(e), chapter: S.n, url: '#' + hashFor({p: 'e:' + c.entity, tab: '', m: ''}),
      text: text || `Looks right: ${c.reason}`, check: id, verdict})});
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || r.status);
  NOTES.count = d.count;
  NOTES.answered.add(id);
  reportLabel();
  render();
}
async function probeNotes() {
  try {
    const r = await fetch('api/notes', {cache: 'no-store'});
    const d = r.ok ? await r.json() : null;
    if (!Array.isArray(d?.notes)) return;
    NOTES.count = d.notes.length;
    NOTES.on = true;
    for (const n of d.notes) if (n.check) NOTES.answered.add(n.check);
    if (S.p === 'checks') render();
    $('report').hidden = false;
    reportLabel();
  } catch (err) { /* a plain static host has no notes endpoint, so the button stays hidden */ }
}
function reportLabel() { $('report').textContent = NOTES.count ? `Report a problem (${NOTES.count})` : 'Report a problem'; }
function pageTitle() { return document.querySelector('#main h1')?.textContent.trim() || 'Home'; }
function openReport() {
  const box = $('reportbox');
  box.innerHTML = `<h4>Report a problem</h4><div class="muted">${esc(pageTitle())} &middot; chapter ${S.n}</div>
    <textarea id="reporttext" rows="5" placeholder="What is wrong here, and what should it say?"></textarea>
    <div class="reportrow"><span class="muted" id="reportmsg"></span><button data-report-cancel>Cancel</button><button class="primary" data-report-save>Save note</button></div>`;
  box.hidden = false;
  if (NOTES.pending) $('reporttext').value = `Wrong: ${D.checks.find(x => x.id === NOTES.pending).reason}\n`;
  $('reporttext').focus();
}
async function saveReport() {
  const text = $('reporttext').value.trim();
  if (!text) return;
  const note = {page: S.p || 'home', title: pageTitle(), chapter: S.n, url: location.hash, text};
  $('reportmsg').textContent = 'Saving...';
  if (NOTES.pending) {
    const id = NOTES.pending;
    try { await answerCheck(id, 'wrong', text); NOTES.pending = null; $('reportbox').hidden = true; }
    catch (err) { $('reportmsg').textContent = `Not saved: ${err.message}`; }
    return;
  }
  try {
    const r = await fetch('api/notes', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(note)});
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || r.status);
    NOTES.count = d.count;
    reportLabel();
    $('reportbox').innerHTML = `<div class="muted">Saved. ${d.count} note${d.count === 1 ? '' : 's'} so far.</div>`;
    setTimeout(() => { $('reportbox').hidden = true; }, 1500);
  } catch (err) { $('reportmsg').textContent = `Not saved: ${err.message}`; }
}

function setN(n) {
  S.n = Math.min(Math.max(1, n), D.book.max);
  store.set(D.storeKey + ':seen', '1');
  cancelAnimationFrame(setN.raf);
  setN.raf = requestAnimationFrame(() => { writeHash(); render(); });
}

const SEARCH = {perType: 5};
function search() {
  const box = $('results');
  if (!searchKey($('q').value)) return box.classList.remove('open');
  const hits = findEntries($('q').value, D.entities.filter(full), (a, b) => visFacts(b.id).length - visFacts(a.id).length);
  const byType = new Map();
  for (const hit of hits) (byType.get(hit.e.type) || byType.set(hit.e.type, []).get(hit.e.type)).push(hit);
  const row = h => `<div data-res="${h.e.id}"${h === hits[0] ? ' class="sel"' : ''} role="option"><span>${hitName(h)}</span><small>ch ${h.e.first}</small></div>`;
  box.innerHTML = [...byType].map(([type, rows]) => `<div class="rgroup" role="group" aria-label="${esc(catName(type))}"><div class="rhead" aria-hidden="true">${esc(catName(type))}<span>${rows.length}</span></div>${rows.slice(0, SEARCH.perType).map(row).join('')}</div>`).join('')
    || '<div class="muted">No matches up to this chapter</div>';
  box.classList.add('open');
}

function jump(id) {
  const to = $(id);
  if (!to) return;
  to.scrollIntoView({block: 'start'});
  (to.hasAttribute('tabindex') ? to : to.querySelector('.ent') || to).focus({preventScroll: true});
}

function toggleIn(set, key) {
  set.has(key) ? set.delete(key) : set.add(key);
  render();
}

function wire() {
  document.addEventListener('mouseover', ev => {
    const el = ev.target.closest('.ent');
    el ? showHover(el) : hideHover();
  });
  document.addEventListener('focusin', ev => {
    const el = ev.target.closest?.('.gnode.ent');
    el ? showHover(el) : hideHover();
  });
  document.addEventListener('click', ev => {
    const act = sel => ev.target.closest(sel);
    let el;
    if (act('[data-gback]')) store.set('graph-focus', '');
    if ((ev.button || ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.altKey) && act('[href]')) return;
    if ((el = act('[data-check-right]'))) return answerCheck(el.dataset.checkRight, 'right').catch(err => alert(`Not saved: ${err.message}`));
    if ((el = act('[data-check-wrong]'))) { NOTES.pending = el.dataset.checkWrong; return openReport(); }
    if (act('[data-report]')) { NOTES.pending = null; return $('reportbox').hidden ? openReport() : ($('reportbox').hidden = true); }
    if (act('[data-report-cancel]')) { NOTES.pending = null; return ($('reportbox').hidden = true); }
    if (act('[data-report-save]')) return saveReport();
    if (act('[data-volend]')) { const v = volumeAt(S.n); if (v && !v.end) setN(v.to); return; }
    if (graphClick(ev, act) || storyClick(ev, act)) return;
    if ((el = act('.disc'))) return toggleDisc(el);
    if ((el = act('.ent'))) { ev.preventDefault(); return go({p: 'e:' + el.dataset.ent, tab: ''}); }
    if ((el = act('[data-res]'))) { $('q').value = ''; $('results').classList.remove('open'); return go({p: 'e:' + el.dataset.res, tab: ''}); }
    if ((el = act('[data-go]'))) { ev.preventDefault(); return go({p: el.dataset.go}); }
    if ((el = act('[data-sec]'))) { ev.preventDefault(); if (el.dataset.in && el.dataset.in !== S.tab) go({tab: el.dataset.in}); return jump('sec-' + el.dataset.sec); }
    if ((el = act('[data-tab]'))) return go({tab: el.dataset.tab});
    if ((el = act('[data-m]'))) { more = 60; return go({m: el.dataset.m}); }
    if ((el = act('[data-sort]'))) {
      ev.preventDefault();
      const key = el.dataset.sort.replace(/^-/, '');
      go({sort: el.dataset.sort});
      return document.querySelector(`.ctable [data-sort="${key}"], .ctable [data-sort="-${key}"]`)?.focus();
    }
    if ((el = act('[data-az]'))) { ev.preventDefault(); if (!$('az-' + el.dataset.az)) go({sort: 'name'}); return jump('az-' + el.dataset.az); }
    if ((el = act('[data-gt]'))) return toggleIn(shownTypes(G.model.view), el.dataset.gt);
    if ((el = act('[data-ggt]'))) { const set = shownTypes(G.model.view); return toggleGroup(groupTypes(TYPE_GROUPS.find(g => g.key === el.dataset.ggt)), t => set.has(t), (t, on) => on ? set.add(t) : set.delete(t)); }
    if ((el = act('[data-ggr]'))) return toggleGroup(REL_GROUPS.find(g => g.key === el.dataset.ggr).fams, f => !G.hideFams.has(f), (f, on) => on ? G.hideFams.delete(f) : G.hideFams.add(f));
    if ((el = act('.gmoref summary'))) { G.moreOpen = !el.parentElement.open; return; }
    if ((el = act('[data-gopt]'))) { G[el.dataset.gopt] = el.checked; return render(); }
    if ((el = act('[data-gz]'))) return G.zoom?.(el.dataset.gz);
    if (act('[data-gfull]')) return toggleFull(!G.full);
    if (act('[data-more]')) { more += 60; return render(); }
    if ((el = act('[data-step]'))) return setN(S.n + +el.dataset.step);
    if (act('#menu')) return document.body.classList.toggle('menu-open');
    if (!act('.side')) document.body.classList.remove('menu-open');
    if (!act('.searchwrap')) document.querySelectorAll('.results.open').forEach(box => box.classList.remove('open'));
  });
  $('theme').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', ev => {
    if (!store.get('wiki-theme')) document.documentElement.dataset.theme = ev.matches ? 'dark' : 'light';
  });
  $('n').addEventListener('input', ev => setN(+ev.target.value));
  $('q').addEventListener('input', search);
  $('q').addEventListener('keydown', ev => {
    if (ev.key === 'Enter') $('results').querySelector('[data-res]')?.click();
    if (ev.key === 'Escape') { $('q').value = ''; $('results').classList.remove('open'); }
  });
  window.addEventListener('hashchange', () => { readHash(); render(); });
  window.addEventListener('resize', () => G.refit?.());
  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && G.full) toggleFull(false); });
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && $('reportbox').hidden === false) return ($('reportbox').hidden = true);
    if (ev.target.id === 'reporttext' && ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) return saveReport();
    if (graphKey(ev)) return;
    if (ev.target.matches('input,textarea')) return;
    if (ev.key === 'Escape' && G.full) return toggleFull(false);
    if (ev.key === '[') setN(S.n - 1);
    if (ev.key === ']') setN(S.n + 1);
    if (ev.key === '/') { ev.preventDefault(); $('q').focus(); }
  });
}

load().then(() => { readHash(); wire(); volumeTicks(); writeHash(); render(); probeNotes(); }).catch(err => {
  $('main').innerHTML = `<p class="muted">Could not load data/wiki.json: ${esc(err.message)}. Serve this folder over HTTP rather than opening the file directly.</p>`;
});
