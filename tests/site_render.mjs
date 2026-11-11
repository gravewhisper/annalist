import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const [app, wikiPath, ...views] = process.argv.slice(2);
const noop = () => {};
const node = () => ({innerHTML: '', textContent: '', value: '', max: 0, dataset: {}, style: {setProperty: noop},
  classList: {add: noop, remove: noop, toggle: noop, contains: () => false},
  addEventListener: noop, querySelector: () => null, querySelectorAll: () => [], appendChild: noop, focus: noop,
  setAttribute: noop, getBoundingClientRect: () => ({left: 0, top: 0, width: 0, height: 0}), clientWidth: 800, clientHeight: 600});
const nodes = {};
const listeners = {};
const document = {getElementById: id => (nodes[id] ||= node()), createElement: node, head: node(), body: node(),
  documentElement: node(), addEventListener: (type, fn) => (listeners[type] ||= []).push(fn), querySelector: () => null, querySelectorAll: () => []};
let url = '';
const context = {document, window: {addEventListener: noop, scrollTo: noop}, location: {hash: ''}, history: {replaceState: (state, title, to) => { url = to; }},
  localStorage: (() => { const kept = new Map(); return {getItem: k => kept.get(k) ?? null, setItem: (k, v) => kept.set(k, String(v))}; })(), matchMedia: () => ({matches: false, addEventListener: noop}),
  fetch: async () => ({json: async () => JSON.parse(readFileSync(wikiPath, 'utf8'))}), console, URLSearchParams,
  requestAnimationFrame: () => 0, cancelAnimationFrame: noop, performance, scrollX: 0, scrollY: 0, innerWidth: 1200};
vm.createContext(context);
vm.runInContext(readFileSync(app, 'utf8') + '\nglobalThis.__app = {S, G, D, renderEntity, renderMysteries, renderGraph, mainCharacter, shownNames, renderHome, renderChapter, renderVolume, counts, graphAt, qState, load, go, search, readHash, REL_GROUPS, TYPE_GROUPS, predicate, questions: () => D.questions, ORBIT, fitView, labelSpots, outward, revealTiming, CAT_COLS};', context);
await context.__app.load();
await new Promise(r => setTimeout(r));

const element = (attrs, parent = null) => {
  const dataset = Object.fromEntries(Object.entries(attrs).filter(([k]) => k.startsWith('data-'))
    .map(([k, v]) => [k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase()), v]));
  const matches = sel => sel.split(',').map(s => s.trim()).some(s =>
    s.startsWith('[') ? s.slice(1, -1) in attrs : s.startsWith('.') ? (attrs.class || '').split(' ').includes(s.slice(1))
      : s.startsWith('#') ? attrs.id === s.slice(1) : false);
  const el = {dataset, parent, checked: false, matches, getAttribute: k => attrs[k] ?? null, setAttribute: (k, v) => { attrs[k] = String(v); },
    closest: sel => { for (let e = el; e; e = e.parent) if (e.matches(sel)) return e; return null; }};
  return el;
};
const graphEl = element({id: 'graph', class: 'graph'});
const target = spec => spec === 'graph' ? graphEl : element({[`data-${spec.split('=')[0]}`]: spec.slice(spec.indexOf('=') + 1)}, graphEl);
const dispatch = (type, ev) => {
  let prevented = false;
  (listeners[type] || []).forEach(fn => fn({clientX: 100, clientY: 100, button: 0, preventDefault: () => { prevented = true; }, stopPropagation: noop, ...ev}));
  return prevented;
};

const fitted = (focus, query) => {
  setGraph('characters', query);
  const m = a.graphAt(focus), [W, H] = [702, 544];
  const spots = [...m.nodes, ...m.bubbles];
  const labels = spots.map(p => { const [ox, oy, anchor] = a.outward(p, p.focus); return {x: p.x, y: p.y, ox, oy, big: !!p.focus, text: p.label, anchor}; });
  const padX = Math.max(...labels.map(l => l.text.length)) * 7 + 24;
  const view = a.fitView(spots.map(p => [p.x, p.y]), W, H, 0, {padX, padY: 36, most: a.ORBIT.most});
  const placed = a.labelSpots(spots.map(p => ({x: p.x, y: p.y, r: p.r})), labels, view.k, [-view.x, -view.y, W - view.x, H - view.y]);
  return {k: view.k, boxes: placed.map(([x, y], i) => { const w = labels[i].text.length * 7 + 4, anchor = labels[i].anchor, left = x * view.k - (anchor === 'end' ? w : anchor === 'start' ? 0 : w / 2); return [left, y * view.k - 9, left + w, y * view.k + 9]; })};
};
const out = {};
const a = context.__app;
const setGraph = (view, query) => {
  const q = new URLSearchParams(query);
  const types = q.getAll('type'), hidden = q.getAll('hideType');
  a.G.types[view] = q.has('allTypes') ? new Set(a.D.typeOrder) : types.length ? new Set(types) : hidden.length ? new Set(a.D.typeOrder.filter(t => !hidden.includes(t))) : null;
  Object.assign(a.G, {hideFams: new Set(q.getAll('hideFam')), erased: q.has('erased'), isolates: q.has('isolates'), allTies: q.has('allTies'),
    limit: +(q.get('limit') || 20), open: new Set(q.getAll('open'))});
};
const graphView = (focus, query) => {
  setGraph(focus === 'all' ? 'all' : /^path(:|$)/.test(focus) ? 'path' : 'characters', query);
  return {model: a.graphAt(focus), html: a.renderGraph(focus)};
};
const routed = () => ({p: a.S.p, full: !!a.G.full, html: nodes.main?.innerHTML ?? '', url});
const links = route => {
  a.go({p: route});
  const html = nodes.main.innerHTML + nodes.side.innerHTML;
  const before = {...a.S};
  const found = [...html.matchAll(/<a ([^>]*\bhref="#[^"]*"[^>]*)>/g)].map(m => Object.fromEntries([...m[1].matchAll(/([\w-]+)="([^"]*)"/g)].map(x => [x[1], x[2]])));
  const rows = found.map(attrs => {
    context.location.hash = attrs.href.replace(/&amp;/g, '&');
    a.readHash();
    const routed = {p: a.S.p, n: a.S.n, tab: a.S.tab, m: a.S.m};
    Object.assign(a.S, before);
    return {go: attrs['data-go'] ?? null, tabTo: attrs['data-tab'] ?? null, mTo: attrs['data-m'] ?? null, ent: attrs['data-ent'] ?? null, ...routed};
  });
  context.location.hash = '';
  return {rows, bare: [...html.matchAll(/<a (?![^>]*\b(?:href=|role="switch"))[^>]*>/g)].map(m => m[0])};
};
const navClick = (mods, p) => {
  const ev = Object.fromEntries(mods.split('+').filter(Boolean).map(k => k === 'middle' ? ['button', 1] : [k + 'Key', true]));
  const before = a.S.p;
  const prevented = dispatch('click', {target: element({'data-go': p, href: '#p=' + p}), ...ev});
  const after = a.S.p;
  a.S.p = before;
  return {prevented, routed: after === p};
};
const toggled = (route, query) => {
  const q = new URLSearchParams(query);
  a.S.m = q.get('m') || '';
  a.S.tab = q.get('tab') || '';
  a.go({p: route});
  const html = nodes.main.innerHTML;
  const found = [...html.matchAll(/<button type="button" class="disc"([^>]*)>(.*?)<\/button>/g)].find(m => m[2].includes(q.get('label') || ''));
  if (!found) return null;
  const attrs = Object.fromEntries([...found[1].matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]));
  const button = element({class: 'disc', ...attrs});
  const panel = document.getElementById(attrs['aria-controls']);
  panel.hidden = html.includes(`id="${attrs['aria-controls']}" hidden`);
  const state = () => ({expanded: button.getAttribute('aria-expanded'), hidden: panel.hidden});
  const steps = [state()];
  for (const _ of [1, 2]) { dispatch('click', {target: button}); steps.push(state()); }
  return steps;
};
for (const view of views) {
  const [page, rest] = view.split('@');
  const [n, query] = rest.split('?');
  const [id, focus] = page.split(/:(.*)/s);
  a.S.n = +n;
  if (id === 'mysteries') a.S.m = new URLSearchParams(query).get('m') || '';
  out[view] = id === 'mysteries' ? a.renderMysteries()
    : id === 'states' ? Object.fromEntries(a.questions().map(q => [q.id, a.qState(q)]))
    : id === 'graph' ? graphView(focus, query)
    : id === 'fitted' ? fitted(focus, query)
    : id === 'reveal' ? a.revealTiming(+focus)
    : id === 'names' ? (([items, k, zoomed, hovered, lit]) => [...a.shownNames(items, k, zoomed, hovered, lit && new Set(lit))])(JSON.parse(view.slice(6, view.lastIndexOf('@'))))
    : id === 'home' ? a.renderHome(a.counts())
    : id === 'chapter' ? a.renderChapter(+focus)
    : id === 'volume' ? a.renderVolume(focus)
    : id === 'route' ? (a.go({p: focus, ...Object.fromEntries(new URLSearchParams(query))}), routed())
    : id === 'toggle' ? toggled(focus, query)
    : id === 'links' ? links(focus)
    : id === 'navclick' ? navClick(focus, new URLSearchParams(query).get('to'))
    : id === 'phrases' ? Object.fromEntries(readFileSync(focus, 'utf8').split('\n').filter(Boolean).map(w => [w, a.predicate(w)]))
    : id === 'tables' ? {rel: a.REL_GROUPS, types: a.TYPE_GROUPS, sorts: a.CAT_COLS.map(c => c.key)}
    : id === 'header' ? {brand: nodes.brand.textContent, title: document.title}
    : id === 'search' ? (document.getElementById('q').value = focus, a.search(), nodes.results.innerHTML)
    : id === 'click' ? (dispatch('click', {target: target(focus)}), routed())
    : id === 'tap' ? (dispatch('click', {target: target(focus), pointerType: 'touch'}), routed())
    : id === 'key' ? (dispatch('keydown', {target: target(focus.slice(0, focus.lastIndexOf(':'))), key: focus.slice(focus.lastIndexOf(':') + 1)}), routed())
    : (a.S.tab = new URLSearchParams(query).get('tab') || '', a.renderEntity(id));
}
console.log(JSON.stringify(out));
