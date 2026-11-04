const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function boot(seed = 42) {
  const listeners = {};
  const drawn = [];
  const ctx = new Proxy({
    measureText: s => ({ width: [...s].length * 6 }),
    fillText: s => drawn.push(s),
    createRadialGradient: () => ({ addColorStop() {} })
  }, { get: (o, k) => k in o ? o[k] : () => {} });
  function element(dataset = {}) {
    return {
      dataset, style: {}, offsetHeight: 96, events: {}, hidden: false,
      addEventListener(k, fn) { this.events[k] = fn; },
      getContext: () => ctx, setPointerCapture() {}
    };
  }
  const buttons = ['arrowup', 'arrowleft', 'arrowdown', 'arrowright', 'e', 'q'].map(key => element({ key }));
  const elements = { game: element(), controls: element(), pause: element(), action: buttons[4] };
  let frame, ts = 1000;
  const math = Object.create(Math);
  math.random = () => { seed = (1664525 * seed + 1013904223) >>> 0; return seed / 4294967296; };
  const sandbox = {
    Math: math, innerWidth: 960, innerHeight: 700, performance: { now: () => ts },
    addEventListener(k, fn) { listeners[k] = fn; },
    requestAnimationFrame(fn) { frame = fn; },
    ResizeObserver: class { observe() {} },
    Image: class { complete = true; naturalWidth = 1200; naturalHeight = 1800; },
    document: {
      hidden: false, getElementById: id => elements[id],
      createElement: () => element(), querySelectorAll: () => buttons,
      addEventListener(k, fn) { listeners[k] = fn; }
    }
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  for (const file of ['assets.js', 'game.js']) vm.runInContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), sandbox);
  function step(seconds = 0.05) {
    for (let t = 0; t < seconds - 1e-8; t += 0.05) { ts += 50; frame(ts); }
  }
  function key(key, repeat = false) {
    listeners.keydown({ key, repeat, target: { tagName: 'BODY' }, preventDefault() {} });
    listeners.keyup({ key });
  }
  frame(ts);
  return {
    get g() { return sandbox.__PG.G; }, get state() { return sandbox.__PG.state; },
    get paused() { return sandbox.__PG.paused; },
    sandbox, listeners, elements, buttons, drawn, key, step,
    start(role = 'dad') { key(role === 'dad' ? 'ArrowLeft' : 'ArrowRight'); key('Enter'); },
    at(x, y = 246) { Object.assign(sandbox.__PG.G.player, { x, y }); },
    time(hour) { sandbox.__PG.G.t = (hour - 6) / 18 * 480; step(); },
    need(who, type, extra = {}) {
      sandbox.__PG.G.needs.push({ who, type, t: 24, max: 24, ...extra });
    }
  };
}

function deliver(b, who, item) {
  const g = b.g;
  const stations = { food: 115, diaper: 191, toy: 256, groceries: 37, bath: 299 };
  if (item) {
    b.at(stations[item]);
    b.key('e');
    assert.equal(g.carry, item);
  } else if (g.carry) b.key('q');
  const recipient = who === 'baby' ? g.baby : g.spouse;
  b.at(recipient.x, recipient.y + 10);
  b.key('e');
}

test('photo-inspired pixel sprites are rectangular and use defined colors', () => {
  const b = boot();
  for (const [name, rows] of Object.entries(b.sandbox.ASSETS)) {
    if (name === 'palette') continue;
    for (const row of rows) {
      assert.equal(row.length, rows[0].length, name);
      for (const pixel of row) assert.ok(pixel === '.' || b.sandbox.ASSETS.palette[pixel], name);
    }
  }
});

test('both roles, movement, collision, bounds, and repeat-key protection', () => {
  for (const role of ['dad', 'mom']) {
    const b = boot();
    assert.equal(b.state, 'title');
    b.start(role);
    assert.equal(b.g.role, role);
    b.listeners.keydown({ key: 'ArrowRight', target: {}, preventDefault() {} });
    b.step(1);
    b.listeners.keyup({ key: 'ArrowRight' });
    assert.ok(b.g.player.x > 320);
    b.at(115, 246);
    b.listeners.keydown({ key: 'ArrowUp', target: {}, preventDefault() {} });
    b.step(1);
    b.listeners.keyup({ key: 'ArrowUp' });
    assert.ok(b.g.player.y >= 240);
    b.listeners.keydown({ key: 'ArrowLeft', target: {}, preventDefault() {} });
    b.step(3);
    b.listeners.keyup({ key: 'ArrowLeft' });
    assert.ok(b.g.player.x >= 12);
    b.at(115);
    b.key('e', true);
    assert.equal(b.g.carry, null);
  }
});

test('grab and deliver every requested item; wrong item does not fulfill', () => {
  for (const [type, item] of [['hungry', 'food'], ['wet', 'diaper'], ['bored', 'toy'], ['bath', 'bath']]) {
    const b = boot(); b.start();
    b.g.baby.x = 318; b.g.baby.y = 248;
    b.need('baby', type);
    b.at(318, 250); b.key('e');
    assert.equal(b.g.needs.length, 1);
    deliver(b, 'baby', item);
    assert.equal(b.g.needs.length, 0, type);
    assert.equal(b.g.stats.ok, 1);
    assert.equal(b.g.carry, null);
  }
});

test('drop and repick items, clean floor, and prioritize actionable family requests', () => {
  const b = boot(); b.start();
  b.at(115); b.key('e');
  b.at(75, 258); b.key('q');
  assert.equal(b.g.drops.length, 1);
  b.key('e');
  assert.equal(b.g.carry, 'food');
  assert.equal(b.g.drops.length, 0);
  b.g.baby.x = 115; b.g.baby.y = 248;
  b.need('baby', 'hungry');
  b.at(115, 241); b.key('e');
  assert.equal(b.g.needs.length, 0);
  b.g.dirty.push({ x: 191, y: 246 });
  b.at(191); b.key('e');
  assert.equal(b.g.dirty.length, 0);
});

test('spouse arrives at 18:00 and handles food, groceries, conversation, and rest', () => {
  for (const [type, item] of [['hungry', 'food'], ['groceries', 'groceries'], ['talk', null], ['tired', null]]) {
    const b = boot(); b.start('mom');
    b.time(17.99); assert.equal(b.g.spouse.home, false);
    b.time(18); assert.equal(b.g.spouse.home, true);
    b.g.needs = [];
    Object.assign(b.g.spouse, { x: 362, y: 232, atSofa: true });
    b.need('spouse', type);
    deliver(b, 'spouse', item);
    assert.equal(b.g.needs.length, 0, type);
  }
});

test('random actionable deadlines, overlapping needs, expiry, and happiness loss', () => {
  const deadlines = new Set();
  for (const seed of [1, 2, 100, 200]) {
    const b = boot(seed); b.start();
    b.step(4.1);
    assert.equal(b.g.needs.length, 1);
    assert.ok(b.g.needs[0].max >= 18 && b.g.needs[0].max <= 28);
    deadlines.add(b.g.needs[0].max);
    b.time(18);
    b.g.spawnT.spouse = 0;
    b.step();
    assert.ok(b.g.needs.some(n => n.who === 'baby'));
    assert.ok(b.g.needs.some(n => n.who === 'spouse'));
    b.g.needs.forEach(n => { n.t = 0.01; });
    b.step();
    assert.equal(b.g.happiness, 72);
    assert.equal(b.g.stats.fail, 2);
  }
  assert.ok(deadlines.size > 1);
});

test('night routine requires bath, dinner, cleanup, bedtime, and soothing before victory', () => {
  const b = boot(); b.start();
  b.time(18.5);
  assert.equal(b.g.needs.find(n => n.who === 'baby').routine, 'bath');
  deliver(b, 'baby', 'bath');
  assert.equal(b.g.routines.bath, true);
  b.g.needs = [];
  b.time(19);
  deliver(b, 'spouse', 'food');
  assert.equal(b.g.routines.dinner, true);
  b.g.needs = [];
  b.time(20);
  assert.ok(b.g.dirty.length);
  for (const spot of [...b.g.dirty]) { b.at(spot.x, spot.y); b.key('e'); }
  assert.equal(b.g.routines.clean, true);
  b.g.needs = [];
  b.time(21);
  deliver(b, 'baby', null);
  assert.equal(b.g.routines.bedtime, true);
  assert.equal(b.g.baby.state, 'sleep');
  b.g.needs = [];
  b.time(22);
  assert.equal(b.g.baby.state, 'awake');
  assert.equal(b.g.needs.find(n => n.who === 'baby').routine, 'soothe');
  deliver(b, 'baby', null);
  assert.equal(b.g.routines.soothe, true);
  b.step(10);
  assert.equal(b.g.baby.state, 'sleep');
  b.time(24);
  assert.equal(b.state, 'win');
  assert.ok(b.drawn.includes('오늘 하루도 무사히 이겨낸 거 축하해!'));
  assert.ok(b.drawn.includes('매일의 도전을 더 즐겁게 맞이하자.'));
  b.key('r');
  assert.equal(b.state, 'title');
  b.start('mom');
  assert.equal(b.g.role, 'mom');
  assert.equal(b.g.happiness, 100);
});

test('expired mandatory needs retry without being incorrectly marked complete', () => {
  const b = boot(); b.start(); b.time(18.5);
  const need = b.g.needs.find(n => n.routine === 'bath');
  need.t = 0.01; b.step();
  assert.equal(b.g.routines.bath, false);
  assert.equal(b.g.happiness, 86);
  b.g.spawnT.baby = Infinity;
  b.step(4.2);
  assert.equal(b.g.needs.find(n => n.who === 'baby').routine, 'bath');
});

test('zero happiness takes precedence over midnight and missing routines cannot win', () => {
  for (const happiness of [0, 100]) {
    const b = boot(); b.start();
    b.g.happiness = happiness;
    b.time(24);
    assert.equal(b.state, 'over');
  }
  const b = boot(); b.start();
  b.g.happiness = 14;
  b.need('baby', 'hungry', { t: 0.01 });
  b.step();
  assert.equal(b.state, 'over');
});

test('touch controls, cancellation, pause, focus loss, and visibility changes are safe', () => {
  const b = boot();
  const right = b.buttons.find(button => button.dataset.key === 'arrowright');
  const action = b.elements.action;
  const pointer = { pointerId: 1, preventDefault() {} };
  right.events.pointerdown(pointer); right.events.pointerup();
  action.events.pointerdown(pointer); action.events.pointerup();
  assert.equal(b.g.role, 'mom');
  right.events.pointerdown(pointer); b.step(0.5); right.events.pointercancel();
  const x = b.g.player.x; b.step(0.2);
  assert.equal(b.g.player.x, x);
  b.elements.pause.events.click();
  const t = b.g.t;
  action.events.pointerdown(pointer); b.step(1);
  assert.equal(b.g.t, t);
  assert.equal(b.paused, true);
  b.key('p'); b.step();
  assert.ok(b.g.t > t);
  b.listeners.blur();
  assert.equal(b.paused, true);
  b.key('Escape');
  b.sandbox.document.hidden = true;
  b.listeners.visibilitychange();
  assert.equal(b.paused, true);
});
