(() => {
  const A = window.ASSETS;
  // Logical resolution 480x270, rendered into a 2x backing store for readability.
  const W = 480, H = 270, HUD_H = 22, SCALE = 2;
  const FLOOR_TOP = 214, FLOOR_BOT = 258;
  const DAY_SECONDS = 480;
  const START_HOUR = 6, END_HOUR = 24, HOME_HOUR = 18;

  const cv = document.getElementById('game');
  const ctx = cv.getContext('2d');

  function fit() {
    const controlsHeight = document.getElementById('controls').offsetHeight;
    const s = Math.min((innerWidth - 16) / W, (innerHeight - controlsHeight - 24) / H);
    cv.style.width = W * s + 'px';
    cv.style.height = H * s + 'px';
  }
  addEventListener('resize', fit);
  new ResizeObserver(fit).observe(document.getElementById('controls'));
  fit();

  function bake(rows, pal) {
    const h = rows.length, w = rows[0].length;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    rows.forEach((r, y) => [...r].forEach((ch, x) => {
      if (pal[ch]) { g.fillStyle = pal[ch]; g.fillRect(x, y, 1, 1); }
    }));
    return c;
  }
  const SPR = {
    dad: [bake(A.dadA, A.palette), bake(A.dadB, A.palette)],
    mom: [bake(A.momA, A.palette), bake(A.momB, A.palette)],
    baby: [bake(A.babyA, A.palette), bake(A.babyB, A.palette)],
    babyLie: bake(A.babyLie, A.palette),
    food: bake(A.food, A.palette), diaper: bake(A.diaper, A.palette),
    toy: bake(A.toy, A.palette), groceries: bake(A.groceries, A.palette),
    talk: bake(A.talk, A.palette), sleep: bake(A.sleep, A.palette),
    heart: bake(A.heart, A.palette), sun: bake(A.sun, A.palette),
    moon: bake(A.moon, A.palette), sparkle: bake(A.sparkle, A.palette),
    bath: bake(A.bath, A.palette)
  };
  const ITEM_LABEL = { food: '밥', diaper: '기저귀', toy: '장난감', groceries: '장보기', bath: '목욕 수건' };

  // ---------- audio ----------
  let AC = null;
  function audio() {
    if (!AC) { try { AC = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { AC = null; } }
    if (AC && AC.state === 'suspended') AC.resume();
    return AC;
  }
  function tone(f, d, type = 'square', vol = 0.05, when = 0) {
    const ac = audio(); if (!ac) return;
    const o = ac.createOscillator(), g = ac.createGain();
    o.type = type; o.frequency.value = f;
    g.gain.setValueAtTime(vol, ac.currentTime + when);
    g.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + when + d);
    o.connect(g); g.connect(ac.destination);
    o.start(ac.currentTime + when); o.stop(ac.currentTime + when + d + 0.02);
  }
  const sfx = {
    click: () => tone(660, 0.06),
    pickup: () => { tone(520, 0.07); tone(780, 0.08, 'square', 0.05, 0.07); },
    ok: () => { tone(523, 0.09); tone(659, 0.09, 'square', 0.05, 0.09); tone(784, 0.15, 'square', 0.05, 0.18); },
    fail: () => { tone(220, 0.18, 'sawtooth', 0.06); tone(160, 0.25, 'sawtooth', 0.06, 0.12); },
    cry: () => { tone(740, 0.09, 'triangle', 0.07); tone(560, 0.13, 'triangle', 0.07, 0.1); },
    bell: () => { tone(880, 0.12); tone(880, 0.12, 'square', 0.05, 0.16); },
    clean: () => tone(980, 0.07, 'sine', 0.05),
    win: () => [523, 659, 784, 1047].forEach((f, i) => tone(f, 0.16, 'square', 0.06, i * 0.14))
  };

  // ---------- text (direct rendering, Korean-safe) ----------
  const FONT_STACK = '"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR","맑은 고딕",sans-serif';
  function text(s, x, y, size, color = '#fff', align = 'left', shadow = 'rgba(0,0,0,0.8)') {
    ctx.font = `bold ${size}px ${FONT_STACK}`;
    ctx.textBaseline = 'top';
    const w = ctx.measureText(s).width;
    if (align === 'center') x -= w / 2; else if (align === 'right') x -= w;
    x = Math.round(x); y = Math.round(y);
    const off = Math.max(1, Math.round(size / 10));
    if (shadow) { ctx.fillStyle = shadow; ctx.fillText(s, x + off, y + off); }
    ctx.fillStyle = color;
    ctx.fillText(s, x, y);
  }
  function rect(x, y, w, h, color) { ctx.fillStyle = color; ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); }

  // ---------- photo ----------
  const photo = new Image();
  const photoPx = document.createElement('canvas');
  photoPx.width = 120; photoPx.height = 68;
  photo.onload = () => {
    const g = photoPx.getContext('2d');
    const scale = Math.max(120 / photo.naturalWidth, 68 / photo.naturalHeight);
    const width = photo.naturalWidth * scale, height = photo.naturalHeight * scale;
    g.drawImage(photo, (120 - width) / 2, (68 - height) / 2, width, height);
  };
  photo.src = 'assets/family-photo.jpg';
  const portrait = new Image();
  portrait.src = 'assets/family-portrait.jpg';

  // ---------- world layout ----------
  const stations = [
    { id: 'door',    x: 18,  y: 150, w: 38, h: 82, item: 'groceries', icon: 'groceries', label: '장보기' },
    { id: 'kitchen', x: 84,  y: 190, w: 62, h: 42, item: 'food',      icon: 'food',      label: '밥' },
    { id: 'changer', x: 168, y: 194, w: 46, h: 38, item: 'diaper',    icon: 'diaper',    label: '기저귀' },
    { id: 'bath',    x: 283, y: 210, w: 32, h: 22, item: 'bath',      icon: 'bath',      label: '목욕' },
    { id: 'toybox',  x: 236, y: 198, w: 40, h: 34, item: 'toy',       icon: 'toy',       label: '장난감' },
    { id: 'sofa',    x: 328, y: 192, w: 68, h: 40, item: null,        icon: 'talk',      label: '대화/휴식' },
    { id: 'crib',    x: 410, y: 190, w: 54, h: 42, item: null,        icon: 'sleep',     label: '잠' }
  ];
  const blockers = stations.map(s => ({ x: s.x + 3, y: s.y + 16, w: s.w - 6, h: s.h - 16 }));
  const WIN = { x: 196, y: 56, w: 76, h: 58 };

  const NEEDS = {
    hungry:    { icon: 'food',      item: 'food',      label: '배고파요!' },
    wet:       { icon: 'diaper',    item: 'diaper',    label: '기저귀 젖음!' },
    bored:     { icon: 'toy',       item: 'toy',       label: '심심해요!' },
    sleepy:    { icon: 'sleep',     item: null,        label: '잠이 와요…' },
    groceries: { icon: 'groceries', item: 'groceries', label: '장 봐줘요!' },
    talk:      { icon: 'talk',      item: null,        label: '이야기해요!' },
    tired:     { icon: 'sleep',     item: null,        label: '피곤해요…' },
    bath:      { icon: 'bath',      item: 'bath',      label: '목욕할래요!' }
  };
  const ROUTINES = {
    bath: { hour: 18.5, who: 'baby', type: 'bath', label: '아기 목욕' },
    dinner: { hour: 19, who: 'spouse', type: 'hungry', label: '저녁 식사' },
    clean: { hour: 20, label: '방 청소' },
    bedtime: { hour: 21, who: 'baby', type: 'sleepy', label: '아기 재우기' },
    soothe: { hour: 22, who: 'baby', type: 'sleepy', label: '다시 재우기' }
  };

  const rand = (a, b) => a + Math.random() * (b - a);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const dist = (x1, y1, x2, y2) => Math.hypot(x2 - x1, y2 - y1);

  // ---------- state ----------
  let state = 'title';
  let sel = 0;               // 0 = dad, 1 = mom
  let G = null;
  let paused = false;

  function newGame() {
    G = {
      t: 0,
      happiness: 100,
      carry: null,
      drops: [],
      role: sel === 0 ? 'dad' : 'mom',
      player: { x: 250, y: 240, dir: 1, frame: 0, animT: 0 },
      baby: { x: 318, y: 248, dir: -1, state: 'awake', sleepT: 0, wakeNeed: false, wx: 300, wy: 240, wanderT: 0, frame: 0, animT: 0, cryT: 0 },
      spouse: { x: 37, y: 240, home: false, atSofa: false, dir: 1, frame: 0, animT: 0, cryT: 0 },
      needs: [],
      spawnT: { baby: 4, spouse: Infinity },
      dirty: [], dirtyT: 14,
      particles: [], toasts: [],
      stats: { ok: 0, fail: 0 },
      flash: 0, nightWakeDone: false,
      routines: { bath: false, dinner: false, clean: false, bedtime: false, soothe: false },
      routineRetry: {}, routineCleanStarted: false
    };
    paused = false;
    clearKeys();
    toast('물건을 집고 가족에게 전달해요! E: 행동 · Q: 내려놓기', 4.5);
  }

  function hour() { return START_HOUR + (G.t / DAY_SECONDS) * (END_HOUR - START_HOUR); }

  function toast(s, life = 2.4) {
    G.toasts.push({ s, t: life });
    if (G.toasts.length > 3) G.toasts.shift();
  }

  function spawnNeed(who) {
    if (G.needs.some(n => n.who === who)) return;
    if (who === 'baby' && (G.routines.bedtime || hour() >= 21)) return;
    const h = hour();
    let pool;
    if (who === 'baby') {
      if (G.baby.state === 'sleep') return;
      pool = ['hungry', 'wet', 'bored'];
      if (h >= 12 && h < 18) { pool.push('sleepy', 'sleepy'); }
    } else {
      pool = ['hungry', 'talk', 'tired', 'groceries'];
    }
    const type = pool[Math.floor(Math.random() * pool.length)];
    const max = who === 'baby' ? rand(18, 28) : rand(18, 25);
    G.needs.push({ who, type, t: max, max });
    if (who === 'baby') sfx.cry();
  }

  function fulfill(n) {
    G.needs = G.needs.filter(x => x !== n);
    G.happiness = clamp(G.happiness + 9, 0, 100);
    G.stats.ok++;
    if (n.routine) G.routines[n.routine] = true;
    G.carry = null;
    sfx.ok();
    const c = n.who === 'baby' ? G.baby : G.spouse;
    for (let i = 0; i < 6; i++)
      G.particles.push({ x: c.x + rand(-8, 8), y: c.y - 24 + rand(-4, 4), vx: rand(-12, 12), vy: rand(-26, -10), t: 0, life: 0.9, spr: 'heart' });
    if (n.who === 'baby' && n.type === 'sleepy') {
      G.baby.state = 'sleep';
      G.baby.x = 437; G.baby.y = 222;
      G.baby.wakeNeed = n.routine === 'bedtime';
      G.baby.sleepT = n.routine ? Infinity : rand(24, 38);
      toast('아기가 잠들었어요… Zzz');
    }
    if (n.who === 'spouse' && n.type === 'tired') toast('배우자가 소파에서 쉬어요.');
  }

  function expireNeed(n) {
    G.needs = G.needs.filter(x => x !== n);
    G.happiness = clamp(G.happiness - 14, 0, 100);
    G.stats.fail++;
    if (n.routine) G.routineRetry[n.routine] = G.t + 4;
    G.flash = 0.5;
    const c = n.who === 'baby' ? G.baby : G.spouse;
    c.cryT = 1.2;
    if (n.who === 'baby') sfx.cry(); else sfx.fail();
    toast(NEEDS[n.type].label.replace('!', '') + ' — 놓쳤어요! 행복도가 줄었어요');
  }

  // ---------- input ----------
  const keys = {};
  addEventListener('keydown', e => {
    const k = e.key.toLowerCase();
    if (e.target.tagName === 'BUTTON' && (k === 'enter' || k === ' ')) return;
    if (['arrowup', 'arrowdown', 'arrowleft', 'arrowright', ' '].includes(k)) e.preventDefault();
    audio();
    keys[k] = true;
    if (!e.repeat) handleKey(k);
  });
  addEventListener('keyup', e => { keys[e.key.toLowerCase()] = false; });

  function clearKeys() {
    Object.keys(keys).forEach(k => { keys[k] = false; });
  }

  function pauseGame() {
    if (state !== 'play') return;
    paused = !paused;
    clearKeys();
    document.getElementById('pause').textContent = paused ? '계속 ▶' : '잠깐 쉬기 Ⅱ';
  }

  addEventListener('blur', () => {
    clearKeys();
    if (state === 'play' && !paused) pauseGame();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && state === 'play' && !paused) pauseGame();
  });
  document.querySelectorAll('[data-key]').forEach(button => {
    const k = button.dataset.key;
    button.addEventListener('pointerdown', e => {
      e.preventDefault();
      button.setPointerCapture(e.pointerId);
      audio();
      keys[k] = true;
      handleKey(k);
    });
    for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      button.addEventListener(event, () => { keys[k] = false; });
    }
    button.addEventListener('click', e => {
      if (e.detail === 0) handleKey(k);
    });
  });
  document.getElementById('pause').addEventListener('click', pauseGame);

  function handleKey(k) {
    if (state === 'title') {
      if (k === 'arrowleft' || k === 'a') { sel = 0; sfx.click(); }
      if (k === 'arrowright' || k === 'd') { sel = 1; sfx.click(); }
      if (k === 'e' || k === 'enter') { sfx.click(); newGame(); state = 'play'; }
    } else if (state === 'play') {
      if (k === 'p' || k === 'escape') { pauseGame(); return; }
      if (paused) return;
      if (k === 'e') interact();
      if (k === 'q') dropItem();
    } else if (state === 'over' || state === 'win') {
      if (k === 'r' || k === 'enter' || k === 'e') {
        sfx.click(); state = 'title'; G = null; clearKeys();
      }
    }
  }

  function dropItem() {
    if (!G.carry) return;
    G.drops.push({ item: G.carry, x: clamp(G.player.x, 20, W - 20), y: clamp(G.player.y, FLOOR_TOP, FLOOR_BOT) });
    toast(ITEM_LABEL[G.carry] + '을/를 내려놓았어요');
    G.carry = null;
    sfx.click();
  }

  function interact() {
    const p = G.player;
    const cands = [];
    for (const s of stations) {
      if (!s.item) continue;   // action-only stations (sofa/crib) never swallow the keypress
      cands.push({ d: dist(p.x, p.y, s.x + s.w / 2, s.y + s.h), r: 32, kind: 'station', s });
    }
    for (const o of [{ who: 'baby', c: G.baby }, { who: 'spouse', c: G.spouse, ok: G.spouse.home }]) {
      if (o.ok === false) continue;
      cands.push({ d: dist(p.x, p.y, o.c.x, o.c.y - 8), r: 28, kind: 'char', o });
    }
    for (const d of G.drops) cands.push({ d: dist(p.x, p.y, d.x, d.y - 4), r: 22, kind: 'drop', drop: d });
    for (const d of G.dirty) cands.push({ d: dist(p.x, p.y, d.x, d.y), r: 24, kind: 'dirty', spot: d });
    const actionable = c => {
      if (c.kind === 'char') {
        const need = G.needs.find(n => n.who === c.o.who);
        return Boolean(need && NEEDS[need.type].item === G.carry);
      }
      return c.kind === 'dirty' && !G.carry;
    };
    cands.sort((a, b) => Number(b.d <= b.r && actionable(b)) - Number(a.d <= a.r && actionable(a)) || a.d - b.d);
    const c = cands.find(x => x.d <= x.r);
    if (!c) { dropItem(); return; }   // E on empty floor drops the item
    if (c.kind === 'station') {
      if (G.carry === c.s.item) return;
      if (G.carry) dropItem();
      G.carry = c.s.item;
      sfx.pickup();
      toast(c.s.label + '을/를 집었어요');
    } else if (c.kind === 'char') {
      tryFulfill(c.o);
    } else if (c.kind === 'drop') {
      if (G.carry) dropItem();
      G.drops = G.drops.filter(x => x !== c.drop);
      G.carry = c.drop.item;
      sfx.pickup();
      toast(ITEM_LABEL[c.drop.item] + '을/를 다시 집었어요');
    } else if (c.kind === 'dirty') {
      if (G.carry) { toast('손이 가득해요! (Q로 버리거나 전달하세요)'); return; }
      G.dirty = G.dirty.filter(x => x !== c.spot);
      if (G.routineCleanStarted && G.dirty.length === 0) G.routines.clean = true;
      G.happiness = clamp(G.happiness + 3, 0, 100);
      sfx.clean();
      for (let i = 0; i < 5; i++)
        G.particles.push({ x: c.spot.x + rand(-6, 6), y: c.spot.y + rand(-4, 4), vx: rand(-8, 8), vy: rand(-20, -6), t: 0, life: 0.7, spr: 'sparkle' });
      toast('방을 깨끗하게 닦았어요!');
    }
  }

  function tryFulfill(o) {
    const n = G.needs.find(x => x.who === o.who);
    if (!n) { toast(o.who === 'baby' ? '아기는 지금 괜찮대요' : '배우자는 지금 괜찮대요'); return; }
    const req = NEEDS[n.type];
    if (req.item) {
      if (G.carry === req.item) fulfill(n);
      else toast('필요한 건 ' + ITEM_LABEL[req.item] + '이에요!');
    } else {
      if (!G.carry) fulfill(n);
      else toast('손이 가득해요! (Q로 버리세요)');
    }
  }

  // ---------- update ----------
  function updateRoutines() {
    const h = hour();
    if (h >= 20 && !G.routineCleanStarted) {
      G.routineCleanStarted = true;
      G.dirty.push({ x: 155, y: 250 });
      toast('저녁 마무리: 목욕 · 식사 · 청소 · 잠자리');
    }
    if (h >= 22 && G.routines.bedtime && !G.nightWakeDone) {
      G.nightWakeDone = true;
      G.baby.state = 'awake';
      G.baby.x = 400; G.baby.y = 246;
      toast('아기가 깼어요. 다시 토닥여 주세요!');
      sfx.cry();
    }
    for (const [id, routine] of Object.entries(ROUTINES)) {
      if (!routine.who || G.routines[id] || h < routine.hour || G.t < (G.routineRetry[id] || 0)) continue;
      if (id === 'bedtime' && !G.routines.bath) continue;
      if (id === 'soothe' && !G.nightWakeDone) continue;
      if (G.needs.some(n => n.who === routine.who)) continue;
      if (routine.who === 'baby' && G.baby.state === 'sleep') continue;
      if (routine.who === 'spouse' && !G.spouse.home) continue;
      const max = rand(24, 34);
      G.needs.push({ who: routine.who, type: routine.type, routine: id, t: max, max });
    }
  }

  function update(dt) {
    if (state !== 'play' || paused) return;
    if (G.happiness <= 0) { state = 'over'; sfx.fail(); return; }
    G.t = Math.min(DAY_SECONDS, G.t + dt);
    const h = hour();
    updateRoutines();

    if (G.dirty.length >= 3) {
      G.happiness = clamp(G.happiness - 1.2 * dt, 0, 100);
      if (Math.random() < dt * 0.5) toast('집이 지저분해요… 청소가 필요해요!');
    }

    if (!G.spouse.home && h >= HOME_HOUR) {
      G.spouse.home = true;
      sfx.bell();
      toast('배우자가 퇴근해서 돌아왔어요!');
      G.spawnT.spouse = rand(5, 8);
    }

    G.spawnT.baby -= dt;
    if (G.spawnT.baby <= 0) {
      spawnNeed('baby');
      G.spawnT.baby = h >= HOME_HOUR ? rand(6, 10) : rand(8, 14);
    }
    if (G.spouse.home) {
      G.spawnT.spouse -= dt;
      if (G.spawnT.spouse <= 0) {
        spawnNeed('spouse');
        G.spawnT.spouse = rand(8, 14);
      }
    }

    for (const n of [...G.needs]) {
      n.t -= dt;
      if (n.t <= 0) expireNeed(n);
    }

    G.dirtyT -= dt;
    if (G.dirtyT <= 0) {
      if (h < 20 && G.dirty.length < 3) G.dirty.push({ x: rand(70, 420), y: rand(242, 252) });
      G.dirtyT = rand(18, 30);
    }

    const p = G.player;
    let dx = 0, dy = 0;
    if (keys['arrowleft'] || keys['a']) dx -= 1;
    if (keys['arrowright'] || keys['d']) dx += 1;
    if (keys['arrowup'] || keys['w']) dy -= 1;
    if (keys['arrowdown'] || keys['s']) dy += 1;
    if (dx || dy) {
      const len = Math.hypot(dx, dy);
      dx /= len; dy /= len;
      const sp = 82;
      const nx = clamp(p.x + dx * sp * dt, 12, W - 12);
      const ny = clamp(p.y + dy * sp * dt, FLOOR_TOP, FLOOR_BOT);
      const box = { x: nx - 4, y: ny - 8, w: 8, h: 8 };
      let hit = false;
      for (const b of blockers)
        if (box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y) { hit = true; break; }
      if (!hit) { p.x = nx; p.y = ny; }
      if (dx) p.dir = dx > 0 ? 1 : -1;
      p.animT += dt;
      if (p.animT > 0.18) { p.animT = 0; p.frame ^= 1; }
    } else p.animT = 0;

    const b = G.baby;
    if (b.cryT > 0) b.cryT -= dt;
    if (b.state === 'sleep') {
      b.sleepT -= dt;
      if (Math.random() < dt * 2) G.particles.push({ x: b.x + rand(-6, 6), y: b.y - 14, vx: rand(-4, 4), vy: -10, t: 0, life: 1.2, spr: 'sleep' });
      if (b.sleepT <= 0) {
        b.state = 'awake';
        b.x = 396; b.y = 236;
        sfx.cry();
        toast('아기가 깼어요!');
        if (b.wakeNeed && !G.nightWakeDone) { G.nightWakeDone = true; G.spawnT.baby = 1.5; }
        else G.spawnT.baby = rand(4, 7);
      }
    } else {
      b.wanderT -= dt;
      if (b.wanderT <= 0) {
        b.wanderT = rand(1.5, 3);
        b.wx = rand(240, 400); b.wy = rand(224, 250);
      }
      const d = dist(b.x, b.y, b.wx, b.wy);
      if (d > 3) {
        const sp = 15;
        const mx = (b.wx - b.x) / d * sp * dt, my = (b.wy - b.y) / d * sp * dt;
        b.x = clamp(b.x + mx, 240, 400);
        b.y = clamp(b.y + my, 224, 252);
        if (mx) b.dir = mx > 0 ? 1 : -1;
        b.animT += dt;
        if (b.animT > 0.25) { b.animT = 0; b.frame ^= 1; }
      }
    }

    const sp = G.spouse;
    if (sp.home && !sp.atSofa) {
      const tx = 362, ty = 232;
      const d = dist(sp.x, sp.y, tx, ty);
      if (d > 4) {
        const s2 = 60;
        sp.x += (tx - sp.x) / d * s2 * dt;
        sp.y += (ty - sp.y) / d * s2 * dt;
        sp.dir = 1;
        sp.animT += dt;
        if (sp.animT > 0.2) { sp.animT = 0; sp.frame ^= 1; }
      } else sp.atSofa = true;
    }
    if (sp.cryT > 0) sp.cryT -= dt;

    for (const pt of [...G.particles]) {
      pt.t += dt;
      pt.x += pt.vx * dt; pt.y += pt.vy * dt;
      if (pt.t > pt.life) G.particles = G.particles.filter(q => q !== pt);
    }
    for (const t of [...G.toasts]) {
      t.t -= dt;
      if (t.t <= 0) G.toasts = G.toasts.filter(q => q !== t);
    }
    if (G.flash > 0) G.flash -= dt;

    if (G.happiness <= 0) { state = 'over'; sfx.fail(); }
    else if (h >= END_HOUR) {
      state = Object.values(G.routines).every(Boolean) && G.baby.state === 'sleep' && G.dirty.length === 0 ? 'win' : 'over';
      if (state === 'win') sfx.win(); else sfx.fail();
    }
  }

  // ---------- sky / time ----------
  const SKY_KEYS = [
    { h: 6,  sky: [191, 224, 240], wall: [243, 231, 211], floor: [168, 133, 92],  lamp: 0 },
    { h: 12, sky: [159, 216, 255], wall: [246, 236, 217], floor: [174, 140, 98],  lamp: 0 },
    { h: 17, sky: [255, 217, 160], wall: [242, 217, 184], floor: [168, 133, 92],  lamp: 0 },
    { h: 19, sky: [138, 111, 184], wall: [201, 168, 160], floor: [140, 108, 78],  lamp: 1 },
    { h: 21, sky: [35, 44, 82],    wall: [92, 92, 124],   floor: [108, 85, 66],   lamp: 1 },
    { h: 24, sky: [35, 44, 82],    wall: [92, 92, 124],   floor: [108, 85, 66],   lamp: 1 }
  ];
  const rgb = c => `rgb(${c[0] | 0},${c[1] | 0},${c[2] | 0})`;
  function skyAt(h) {
    h = clamp(h, 6, 24);
    let i = 0;
    while (i < SKY_KEYS.length - 2 && SKY_KEYS[i + 1].h < h) i++;
    const a = SKY_KEYS[i], b = SKY_KEYS[i + 1];
    const f = clamp((h - a.h) / (b.h - a.h), 0, 1);
    const lerp = (u, v) => u + (v - u) * f;
    return {
      sky: [lerp(a.sky[0], b.sky[0]), lerp(a.sky[1], b.sky[1]), lerp(a.sky[2], b.sky[2])],
      wall: [lerp(a.wall[0], b.wall[0]), lerp(a.wall[1], b.wall[1]), lerp(a.wall[2], b.wall[2])],
      floor: [lerp(a.floor[0], b.floor[0]), lerp(a.floor[1], b.floor[1]), lerp(a.floor[2], b.floor[2])],
      lamp: a.lamp || (f > 0.5 ? b.lamp : 0)
    };
  }
  const stars = Array.from({ length: 14 }, () => ({ x: rand(0, 1), y: rand(0, 1), s: Math.random() < 0.3 ? 2 : 1 }));

  function clockText(h) {
    const hh = Math.floor(h), mm = Math.floor((h - hh) * 60);
    const period = hh < 12 ? '오전' : hh < 18 ? '오후' : '밤';
    const dh = hh % 12 === 0 ? 12 : hh % 12;
    return `${period} ${dh}:${String(mm).padStart(2, '0')}`;
  }

  // ---------- render ----------
  function drawSprite(c, x, y, sc, flip) {
    x = Math.round(x); y = Math.round(y);
    ctx.save();
    if (flip) { ctx.translate(x + c.width * sc, y); ctx.scale(-1, 1); ctx.drawImage(c, 0, 0, c.width * sc, c.height * sc); }
    else ctx.drawImage(c, x, y, c.width * sc, c.height * sc);
    ctx.restore();
  }

  function drawRoom(h) {
    const s = skyAt(h);
    rect(0, HUD_H, W, H - HUD_H, rgb(s.wall));
    rect(0, 232, W, H - 232, rgb(s.floor));
    ctx.fillStyle = 'rgba(0,0,0,0.12)';
    for (let x = 0; x < W; x += 32) ctx.fillRect(x, 232, 1, H - 232);
    ctx.fillRect(0, 232, W, 2);
    // window with dynamic sky
    rect(WIN.x - 4, WIN.y - 4, WIN.w + 8, WIN.h + 8, '#8a6a44');
    rect(WIN.x, WIN.y, WIN.w, WIN.h, rgb(s.sky));
    if (h >= 19.5 || h < 6.5) {
      for (const st of stars) {
        const sx = WIN.x + 4 + st.x * (WIN.w - 8), sy = WIN.y + 4 + st.y * (WIN.h - 8);
        rect(sx, sy, st.s, st.s, '#fff');
      }
      drawSprite(SPR.moon, WIN.x + WIN.w - 22, WIN.y + 8, 2, false);
    } else {
      const f = clamp((h - 6) / 12, 0, 1);
      const sx = WIN.x + 8 + f * (WIN.w - 24);
      const sy = WIN.y + WIN.h - 12 - Math.sin(f * Math.PI) * (WIN.h - 24);
      drawSprite(SPR.sun, sx, sy, 2, false);
    }
    rect(WIN.x + WIN.w / 2 - 1, WIN.y, 2, WIN.h, '#8a6a44');
    rect(WIN.x, WIN.y + WIN.h / 2 - 1, WIN.w, 2, '#8a6a44');
    // wall picture
    rect(300, 66, 34, 26, '#8a6a44');
    rect(303, 69, 28, 20, '#f2e6c9');
    drawSprite(SPR.heart, 310, 72, 2, false);
    // rug
    ctx.fillStyle = '#d9a0a8';
    ctx.beginPath(); ctx.ellipse(240, 246, 92, 10, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#c98a94';
    ctx.beginPath(); ctx.ellipse(240, 246, 70, 7, 0, 0, Math.PI * 2); ctx.fill();

    drawFurniture(s);

    // station labels + item icons (so the player can see what each station holds)
    for (const st of stations) {
      const cx = st.x + st.w / 2;
      drawSprite(SPR[st.icon], cx - 8, st.y - 18, 2, false);
      text(st.label, cx, st.y - 34, 10, '#fff', 'center');
    }

    // dropped items on the floor
    for (const d of G ? G.drops : []) drawSprite(SPR[d.item], d.x - 8, d.y - 12, 2, false);

    // dirty spots: gray stains (not brown blobs)
    for (const d of G ? G.dirty : []) {
      rect(d.x - 6, d.y - 1, 5, 3, '#9aa2b5');
      rect(d.x - 1, d.y - 3, 4, 3, '#b7bdcc');
      rect(d.x + 3, d.y, 5, 2, '#8b93a7');
      rect(d.x - 3, d.y + 2, 7, 2, '#a7aec0');
    }
  }

  function drawFurniture(s) {
    // door
    rect(18, 150, 38, 82, '#7d5a36');
    rect(23, 158, 12, 28, '#6e4d2d');
    rect(39, 158, 12, 28, '#6e4d2d');
    rect(23, 192, 12, 32, '#6e4d2d');
    rect(39, 192, 12, 32, '#6e4d2d');
    rect(50, 196, 3, 3, '#f2d05a');
    // plant
    rect(60, 218, 12, 14, '#b5533c');
    ctx.fillStyle = '#5da344';
    ctx.beginPath(); ctx.ellipse(66, 210, 9, 12, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#8fd06a';
    ctx.beginPath(); ctx.ellipse(64, 206, 5, 7, -0.4, 0, Math.PI * 2); ctx.fill();
    // kitchen counter
    rect(84, 196, 62, 36, '#d8d3c8');
    rect(84, 192, 62, 6, '#f2efe6');
    rect(90, 199, 18, 12, '#9aa0b0');
    rect(116, 200, 8, 8, '#191919');
    rect(128, 200, 8, 8, '#191919');
    // changing table
    rect(168, 200, 46, 10, '#f2efe6');
    rect(172, 210, 5, 22, '#8a6a44');
    rect(205, 210, 5, 22, '#8a6a44');
    drawSprite(SPR.diaper, 184, 193, 1, false);
    // toy box
    rect(236, 210, 40, 22, '#8a5a3a');
    rect(236, 206, 40, 6, '#a5713f');
    drawSprite(SPR.toy, 250, 198, 1, false);
    // sofa
    rect(328, 200, 68, 32, '#c96f6f');
    rect(328, 194, 14, 38, '#b25a5a');
    rect(382, 194, 14, 38, '#b25a5a');
    rect(342, 196, 26, 14, '#e08a8a');
    rect(368, 196, 14, 14, '#e08a8a');
    // crib
    rect(410, 196, 54, 10, '#f2efe6');
    rect(410, 196, 6, 36, '#e8e2d4');
    rect(458, 196, 6, 36, '#e8e2d4');
    for (let i = 0; i < 5; i++) rect(420 + i * 8, 200, 3, 32, '#e8e2d4');
    rect(416, 224, 42, 8, '#aee2f5');
    rect(414, 220, 12, 6, '#ffffff');
    rect(283, 218, 32, 12, '#aee2f5');
    rect(281, 215, 36, 5, '#ffffff');
    rect(287, 230, 4, 2, '#8a6a44');
    rect(307, 230, 4, 2, '#8a6a44');
    if (s.lamp) {
      const g = ctx.createRadialGradient(294, 194, 4, 294, 194, 90);
      g.addColorStop(0, 'rgba(242,208,90,0.35)');
      g.addColorStop(1, 'rgba(242,208,90,0)');
      ctx.fillStyle = g;
      ctx.fillRect(204, 104, 180, 150);
    }
  }

  function drawChar(c, sprKey) {
    const frames = SPR[sprKey];
    const spr = frames[c.frame & 1];
    const jitter = c.cryT > 0 ? Math.sin(performance.now() / 40) * 1.2 : 0;
    drawSprite(spr, c.x - spr.width + jitter, c.y - spr.height * 2, 2, c.dir < 0);
  }

  function drawNeedBubble(x, y, n) {
    const label = NEEDS[n.type].label;
    ctx.font = `bold 10px ${FONT_STACK}`;
    ctx.textBaseline = 'top';
    const lw = ctx.measureText(label).width;
    const w = Math.max(34, lw + 26), h = 26;
    const bx = Math.round(clamp(x - w / 2, 2, W - w - 2)), by = Math.round(y - 62);
    rect(bx - 1, by - 1, w + 2, h + 2, '#191919');
    rect(bx, by, w, h, '#ffffff');
    drawSprite(SPR[NEEDS[n.type].icon], bx + 3, by + 5, 2, false);
    ctx.fillStyle = '#191919';
    ctx.fillText(label, bx + 22, by + 5);
    const f = clamp(n.t / n.max, 0, 1);
    rect(bx + 2, by + h - 6, w - 4, 4, '#e0e0e0');
    rect(bx + 2, by + h - 6, (w - 4) * f, 4, f > 0.5 ? '#58d68d' : f > 0.25 ? '#f2d05a' : '#c94f4f');
  }

  function drawHUD(h) {
    rect(0, 0, W, HUD_H, '#14141f');
    rect(0, HUD_H - 1, W, 1, '#2c2c44');
    text('행복도', 6, 6, 11, '#f7f0dc');
    rect(48, 7, 104, 9, '#000');
    rect(49, 8, 102, 7, '#3a3a52');
    const v = clamp(G.happiness, 0, 100);
    const col = v > 50 ? '#58d68d' : v > 25 ? '#f2d05a' : '#c94f4f';
    rect(49, 8, 102 * v / 100, 7, col);
    drawSprite(SPR.heart, 158, 7, 1, false);
    const night = h >= 19 || h < 6;
    drawSprite(night ? SPR.moon : SPR.sun, 236, 6, 1, false);
    text(clockText(h), 248, 6, 11, '#fff');
    if (G.carry) {
      text(ITEM_LABEL[G.carry], 440, 6, 11, '#f2d05a', 'right');
      drawSprite(SPR[G.carry], 446, 6, 1, false);
    } else {
      text('손: 비었음', 474, 6, 11, '#c9c9d4', 'right');
    }
  }

  function drawToasts() {
    ctx.font = `bold 12px ${FONT_STACK}`;
    ctx.textBaseline = 'top';
    for (const t of G.toasts.slice(-1)) {
      const size = Math.min(12, 12 * 350 / Math.max(1, ctx.measureText(t.s).width));
      ctx.font = `bold ${size}px ${FONT_STACK}`;
      const w = ctx.measureText(t.s).width + 16;
      rect(290 - w / 2, 30, w, 18, 'rgba(10,10,20,0.85)');
      ctx.fillStyle = '#fff';
      ctx.fillText(t.s, 290 - ctx.measureText(t.s).width / 2, 33);
    }
  }

  function render() {
    ctx.imageSmoothingEnabled = false;
    if (state === 'title') { renderTitle(); return; }
    const h = hour();
    drawRoom(h);

    const ents = [];
    if (G.spouse.home) ents.push({ y: G.spouse.y, f: () => drawChar(G.spouse, G.role === 'dad' ? 'mom' : 'dad') });
    ents.push({
      y: G.baby.y,
      f: () => {
        if (G.baby.state === 'sleep') drawSprite(SPR.babyLie, G.baby.x - 14, G.baby.y - 13, 2, false);
        else drawChar(G.baby, 'baby');
      }
    });
    ents.push({ y: G.player.y, f: () => drawChar(G.player, G.role) });
    ents.sort((a, b) => a.y - b.y).forEach(e => e.f());

    if (G.carry) drawSprite(SPR[G.carry], G.player.x - 8, G.player.y - 56, 2, false);

    for (const n of G.needs) {
      const c = n.who === 'baby' ? G.baby : G.spouse;
      const lift = n.who === 'spouse' && G.needs.some(other => other.who === 'baby') && Math.abs(G.baby.x - c.x) < 130 ? 34 : 0;
      drawNeedBubble(c.x, c.y - 26 - lift, n);
    }
    if (G.baby.state === 'sleep') {
      ctx.font = `bold 10px ${FONT_STACK}`;
      ctx.fillStyle = '#aee2f5';
      ctx.fillText('Zzz', G.baby.x + 12 + Math.sin(performance.now() / 300) * 3, G.baby.y - 34);
    }

    for (const p of G.particles) {
      ctx.globalAlpha = clamp(1 - p.t / p.life, 0, 1);
      drawSprite(SPR[p.spr], p.x - 4, p.y - 4, 1, false);
    }
    ctx.globalAlpha = 1;

    drawHUD(h);
    drawToasts();
    rect(4, 29, 91, 91, 'rgba(20,20,31,0.75)');
    text('오늘의 마무리', 8, 34, 10, '#fff');
    Object.entries(ROUTINES).forEach(([id, routine], i) => {
      text(`${G.routines[id] ? '✓' : '○'} ${routine.label}`, 8, 50 + i * 14, 10, G.routines[id] ? '#8fd06a' : '#fff');
    });

    if (G.flash > 0) {
      ctx.fillStyle = `rgba(201,79,79,${G.flash * 0.35})`;
      ctx.fillRect(0, HUD_H, W, H - HUD_H);
    }

    if (state === 'over') renderOver();
    if (state === 'win') renderWin();
    if (paused && state === 'play') {
      dim(0.75);
      text('잠깐 쉬어가요', W / 2, 106, 26, '#f2d05a', 'center');
      text('P / Esc 또는 계속 버튼으로 돌아오기', W / 2, 149, 12, '#fff', 'center');
    }
    document.getElementById('pause').hidden = state !== 'play';
    document.getElementById('pause').textContent = paused ? '계속 ▶' : '잠깐 쉬기 Ⅱ';
    document.getElementById('action').textContent = state === 'play' ? '행동 E' : '선택 화면';
  }

  function dim(alpha) { ctx.fillStyle = `rgba(5,5,14,${alpha})`; ctx.fillRect(0, 0, W, H); }

  function renderTitle() {
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(photoPx, 0, 0, W, H);
    ctx.imageSmoothingEnabled = false;
    dim(0.62);
    text('PARENTING', W / 2, 20, 34, '#f2d05a', 'center');
    text('가족의 하루를 지켜라', W / 2, 64, 15, '#fff', 'center');
    const cards = [
      { x: 110, label: '아빠', spr: 'dad' },
      { x: 270, label: '엄마', spr: 'mom' }
    ];
    cards.forEach((c, i) => {
      const on = sel === i;
      rect(c.x, 92, 100, 88, on ? '#f2d05a' : '#3a3a52');
      rect(c.x + 2, 94, 96, 84, on ? '#2c2c1a' : '#191926');
      const spr = SPR[c.spr][0];
      drawSprite(spr, c.x + 50 - spr.width, 98, 2, false);
      text(c.label, c.x + 50, 148, 16, on ? '#f2d05a' : '#c9c9d4', 'center');
      if (on) text('◀ 선택됨 ▶', c.x + 50, 166, 11, '#58d68d', 'center');
    });
    document.getElementById('action').textContent = '시작 ▶';
    document.getElementById('pause').hidden = true;
    text('← → 또는 A/D: 캐릭터 선택    E / 시작 버튼', W / 2, 192, 11, '#fff', 'center');
    text('방향키: 이동 · E: 집기/전달 · Q: 내려놓기 · P: 쉬기', W / 2, 208, 11, '#c9c9d4', 'center');
    text('화면 아래 버튼으로도 플레이할 수 있어요', W / 2, 224, 11, '#c9c9d4', 'center');
    text('8분의 하루 · 18시 배우자 귀가 · 저녁 할 일을 모두 마쳐요', W / 2, 240, 11, '#c9c9d4', 'center');
    text('목욕 → 저녁 → 청소 → 잠자리 → 다시 재우기', W / 2, 256, 11, '#58d68d', 'center');
  }

  function renderOver() {
    dim(0.72);
    text(G.happiness <= 0 ? '행복도가 0이 되었어요…' : '아직 남은 일이 있어요…', W / 2, 96, 24, '#c94f4f', 'center');
    text('오늘은 여기까지! 내일은 더 잘할 수 있어요.', W / 2, 136, 12, '#fff', 'center');
    text(`성공 ${G.stats.ok} · 실패 ${G.stats.fail}`, W / 2, 160, 12, '#f2d05a', 'center');
    text('R / 행동 버튼: 다시 선택하기', W / 2, 196, 18, '#58d68d', 'center');
  }

  function renderWin() {
    dim(0.55);
    [photo, portrait].forEach((image, i) => {
      const x = 151 + i * 94, y = 16, width = 84, height = 126;
      rect(x - 3, y - 3, width + 6, height + 6, '#f2d05a');
      if (image.complete && image.naturalWidth) {
        const scale = Math.min(width / image.naturalWidth, height / image.naturalHeight);
        const pw = image.naturalWidth * scale, ph = image.naturalHeight * scale;
        ctx.imageSmoothingEnabled = true;
        ctx.drawImage(image, x + (width - pw) / 2, y + (height - ph) / 2, pw, ph);
      } else {
        rect(x, y, width, height, '#3a3a52');
        text('우리 가족 ♥', x + width / 2, y + 50, 11, '#fff', 'center');
      }
    });
    ctx.imageSmoothingEnabled = false;
    const ty = 153;
    text('오늘 하루도 무사히 이겨낸 거 축하해!', W / 2, ty, 17, '#f2d05a', 'center');
    text('매일의 도전을 더 즐겁게 맞이하자.', W / 2, ty + 24, 17, '#fff', 'center');
    text(`요청 성공 ${G.stats.ok} · 놓친 요청 ${G.stats.fail} · 06:00 → 24:00 생존!`, W / 2, ty + 52, 11, '#c9c9d4', 'center');
    text('R / 행동 버튼: 내일도 도전하기', W / 2, ty + 72, 18, '#58d68d', 'center');
  }

  // ---------- loop ----------
  window.__PG = { get state() { return state; }, get G() { return G; }, get paused() { return paused; } };
  let last = 0;
  function frame(ts) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, last ? (ts - last) / 1000 : 0);
    last = ts;
    ctx.setTransform(SCALE, 0, 0, SCALE, 0, 0);
    update(dt);
    render();
  }
  requestAnimationFrame(frame);
})();
