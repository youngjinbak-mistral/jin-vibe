(() => {
  const A = window.ASSETS;
  const W = 480, H = 270, HUD_H = 22;
  const FLOOR_TOP = 214, FLOOR_BOT = 258;
  const DAY_SECONDS = 300;            // 06:00 -> 24:00 in 5 real minutes
  const START_HOUR = 6, END_HOUR = 24, HOME_HOUR = 18;

  const cv = document.getElementById('game');
  const ctx = cv.getContext('2d');

  function fit() {
    const r = Math.min(innerWidth / W, innerHeight / H);
    const s = r >= 1 ? Math.floor(r) : r;
    cv.style.width = W * s + 'px';
    cv.style.height = H * s + 'px';
  }
  addEventListener('resize', fit);
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
    food: bake(A.food, A.palette), diaper: bake(A.diaper, A.palette),
    toy: bake(A.toy, A.palette), groceries: bake(A.groceries, A.palette),
    talk: bake(A.talk, A.palette), sleep: bake(A.sleep, A.palette),
    heart: bake(A.heart, A.palette), sun: bake(A.sun, A.palette),
    moon: bake(A.moon, A.palette), sparkle: bake(A.sparkle, A.palette)
  };

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

  // ---------- pixel text ----------
  const tcache = new Map();
  function textCanvas(s, px, color) {
    const key = s + '@' + px + '@' + color;
    if (tcache.has(key)) return tcache.get(key);
    const c = document.createElement('canvas');
    const g = c.getContext('2d');
    g.font = `bold ${px}px "Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif`;
    c.width = Math.ceil(g.measureText(s).width) + 2;
    c.height = px + 4;
    const g2 = c.getContext('2d');
    g2.font = g.font; g2.textBaseline = 'top'; g2.fillStyle = color;
    g2.fillText(s, 1, 1);
    tcache.set(key, c);
    return c;
  }
  function text(s, x, y, sc, color = '#fff', align = 'left', shadow = '#000') {
    const c = textCanvas(s, 8, color);
    const w = c.width * sc, h = c.height * sc;
    if (align === 'center') x -= w / 2; else if (align === 'right') x -= w;
    x = Math.round(x); y = Math.round(y);
    ctx.imageSmoothingEnabled = false;
    if (shadow) ctx.drawImage(textCanvas(s, 8, shadow), x + sc, y + sc, w, h);
    ctx.drawImage(c, x, y, w, h);
  }
  function rect(x, y, w, h, color) { ctx.fillStyle = color; ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); }

  // ---------- photo ----------
  const photo = new Image();
  const photoPx = document.createElement('canvas');
  photoPx.width = 120; photoPx.height = 68;
  photo.onload = () => {
    const g = photoPx.getContext('2d');
    g.drawImage(photo, 0, 0, 120, 68);
  };
  photo.src = 'assets/family-photo.jpg';

  // ---------- world layout ----------
  const stations = [
    { id: 'door',    x: 18,  y: 150, w: 38, h: 82, item: 'groceries', label: '장보기' },
    { id: 'kitchen', x: 84,  y: 190, w: 62, h: 42, item: 'food',      label: '밥' },
    { id: 'changer', x: 168, y: 194, w: 46, h: 38, item: 'diaper',    label: '기저귀' },
    { id: 'toybox',  x: 236, y: 198, w: 40, h: 34, item: 'toy',       label: '장난감' },
    { id: 'sofa',    x: 328, y: 192, w: 68, h: 40, item: null,        label: '소파' },
    { id: 'crib',    x: 410, y: 190, w: 54, h: 42, item: null,        label: '아기 침대' }
  ];
  const blockers = stations.map(s => ({ x: s.x + 3, y: s.y + 16, w: s.w - 6, h: s.h - 16 }));
  const WIN = { x: 196, y: 56, w: 76, h: 58 };

  const NEEDS = {
    hungry:    { icon: 'food',      item: 'food',      label: '배고파요!' },
    wet:       { icon: 'diaper',    item: 'diaper',    label: '기저귀 젖었어요!' },
    bored:     { icon: 'toy',       item: 'toy',       label: '심심해요!' },
    sleepy:    { icon: 'sleep',     item: null,        label: '잠이 와요…' },
    groceries: { icon: 'groceries', item: 'groceries', label: '장 좀 봐줘요!' },
    talk:      { icon: 'talk',      item: null,        label: '이야기해요!' },
    tired:     { icon: 'sleep',     item: null,        label: '피곤해요…' }
  };

  const rand = (a, b) => a + Math.random() * (b - a);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const dist = (x1, y1, x2, y2) => Math.hypot(x2 - x1, y2 - y1);

  // ---------- state ----------
  let state = 'title';
  let sel = 0;               // 0 = dad, 1 = mom
  let G = null;

  function newGame() {
    G = {
      t: 0,
      happiness: 100,
      carry: null,
      role: sel === 0 ? 'dad' : 'mom',
      player: { x: 250, y: 240, dir: 1, frame: 0, animT: 0 },
      baby: { x: 300, y: 240, dir: -1, state: 'awake', sleepT: 0, wakeNeed: false, need: null, wx: 300, wy: 240, wanderT: 0, frame: 0, animT: 0, cryT: 0 },
      spouse: { x: 37, y: 240, home: false, atSofa: false, need: null, dir: 1, frame: 0, animT: 0 },
      needs: [],
      spawnT: { baby: 4, spouse: Infinity },
      dirty: [], dirtyT: 14,
      particles: [], toasts: [],
      stats: { ok: 0, fail: 0 },
      flash: 0, nightWakeDone: false
    };
    toast('이동: WASD/방향키 · E: 집기/전달 · 자정까지 행복도를 지켜라!', 4);
  }

  function hour() { return START_HOUR + (G.t / DAY_SECONDS) * (END_HOUR - START_HOUR); }

  function toast(s, life = 2.4) {
    G.toasts.push({ s, t: life });
    if (G.toasts.length > 3) G.toasts.shift();
  }

  function spawnNeed(who) {
    if (G.needs.some(n => n.who === who)) return;
    const h = hour();
    let pool;
    if (who === 'baby') {
      if (G.baby.state === 'sleep') return;
      pool = ['hungry', 'wet', 'bored'];
      if (h >= 12) { pool.push('sleepy', 'sleepy'); }
    } else {
      pool = ['hungry', 'talk', 'tired', 'groceries'];
    }
    const type = pool[Math.floor(Math.random() * pool.length)];
    const max = who === 'baby' ? rand(11, 19) : rand(10, 17);
    G.needs.push({ who, type, t: max, max });
    if (who === 'baby') sfx.cry();
  }

  function fulfill(n) {
    G.needs = G.needs.filter(x => x !== n);
    G.happiness = clamp(G.happiness + 9, 0, 100);
    G.stats.ok++;
    G.carry = null;
    sfx.ok();
    const c = n.who === 'baby' ? G.baby : G.spouse;
    for (let i = 0; i < 6; i++)
      G.particles.push({ x: c.x + rand(-8, 8), y: c.y - 24 + rand(-4, 4), vx: rand(-12, 12), vy: rand(-26, -10), t: 0, life: 0.9, spr: 'heart' });
    if (n.who === 'baby' && n.type === 'sleepy') {
      G.baby.state = 'sleep';
      G.baby.x = 437; G.baby.y = 222;
      const h = hour();
      G.baby.wakeNeed = h >= 20;
      G.baby.sleepT = h >= 20 ? rand(5, 9) : rand(24, 38);
      toast('아기가 잠들었어요… Zzz');
    }
    if (n.who === 'spouse' && n.type === 'tired') toast('배우자가 소파에서 쉬어요.');
  }

  function expireNeed(n) {
    G.needs = G.needs.filter(x => x !== n);
    G.happiness = clamp(G.happiness - 14, 0, 100);
    G.stats.fail++;
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
    if (['arrowup', 'arrowdown', 'arrowleft', 'arrowright', ' '].includes(k)) e.preventDefault();
    audio();
    keys[k] = true;
    handleKey(k);
  });
  addEventListener('keyup', e => { keys[e.key.toLowerCase()] = false; });

  function handleKey(k) {
    if (state === 'title') {
      if (k === 'arrowleft' || k === 'a') { sel = 0; sfx.click(); }
      if (k === 'arrowright' || k === 'd') { sel = 1; sfx.click(); }
      if (k === 'e' || k === 'enter') { sfx.click(); newGame(); state = 'play'; }
    } else if (state === 'play') {
      if (k === 'e') interact();
    } else if (state === 'over' || state === 'win') {
      if (k === 'r') { sfx.click(); newGame(); state = 'play'; }
    }
  }

  function interact() {
    const p = G.player;
    // nearest station with an item
    let best = null, bestD = 30;
    for (const s of stations) {
      const d = dist(p.x, p.y, s.x + s.w / 2, s.y + s.h);
      if (d < bestD) { bestD = d; best = { kind: 'station', s }; }
    }
    // characters
    const chars = [{ who: 'baby', c: G.baby }, { who: 'spouse', c: G.spouse, ok: G.spouse.home }];
    let bc = null, bd = 27;
    for (const o of chars) {
      if (o.ok === false) continue;
      const d = dist(p.x, p.y, o.c.x, o.c.y - 8);
      if (d < bd) { bd = d; bc = o; }
    }
    // dirty spots
    let bd2 = 22, bspot = null;
    for (const d of G.dirty) {
      const dd = dist(p.x, p.y, d.x, d.y);
      if (dd < bd2) { bd2 = dd; bspot = d; }
    }

    if (bc && bd <= bestD && bd <= bd2) { tryFulfill(bc); return; }
    if (best && bestD <= bd2) {
      const s = best.s;
      if (!s.item) return;
      if (G.carry === s.item) return;
      G.carry = s.item;
      sfx.pickup();
      toast(s.label + (G.carry ? '을/를 집었어요' : ''));
      return;
    }
    if (bspot) {
      if (G.carry) { toast('손이 가득해요!'); return; }
      G.dirty = G.dirty.filter(d => d !== bspot);
      G.happiness = clamp(G.happiness + 3, 0, 100);
      sfx.clean();
      for (let i = 0; i < 5; i++)
        G.particles.push({ x: bspot.x + rand(-6, 6), y: bspot.y + rand(-4, 4), vx: rand(-8, 8), vy: rand(-20, -6), t: 0, life: 0.7, spr: 'sparkle' });
      toast('방을 깨끗하게 닦았어요!');
    }
  }

  function tryFulfill(o) {
    const n = G.needs.find(x => x.who === o.who);
    if (!n) { toast(o.who === 'baby' ? '아기는 지금 괜찮대요' : '배우자는 지금 괜찮대요'); return; }
    const req = NEEDS[n.type];
    if (req.item) {
      if (G.carry === req.item) fulfill(n);
      else toast('필요한 건 ' + stations.find(s => s.item === req.item).label + '이에요!');
    } else {
      if (!G.carry) fulfill(n);
      else toast('손이 가득해요! 다른 물건으로 바꿔주세요.');
    }
  }

  // ---------- update ----------
  function update(dt) {
    if (state !== 'play') return;
    G.t += dt;
    const h = hour();
    if (h >= END_HOUR) { state = 'win'; sfx.win(); return; }

    if (G.dirty.length >= 3) {
      G.happiness = clamp(G.happiness - 1.2 * dt, 0, 100);
      if (Math.random() < dt * 0.5) toast('집이 지저분해요… 청소가 필요해요!');
    }

    // spouse comes home at 18:00
    if (!G.spouse.home && h >= HOME_HOUR) {
      G.spouse.home = true;
      sfx.bell();
      toast('배우자가 퇴근해서 돌아왔어요!');
      G.spawnT.spouse = rand(5, 8);
    }

    // need spawns
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

    // need timers
    for (const n of [...G.needs]) {
      n.t -= dt;
      if (n.t <= 0) expireNeed(n);
    }

    // dirty spots
    G.dirtyT -= dt;
    if (G.dirtyT <= 0) {
      if (G.dirty.length < 3) G.dirty.push({ x: rand(70, 420), y: rand(224, 252) });
      G.dirtyT = rand(18, 30);
    }

    // player movement
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
      let nx = clamp(p.x + dx * sp * dt, 12, W - 12);
      let ny = clamp(p.y + dy * sp * dt, FLOOR_TOP, FLOOR_BOT);
      const box = { x: nx - 4, y: ny - 8, w: 8, h: 8 };
      let hit = false;
      for (const b of blockers)
        if (box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y) { hit = true; break; }
      if (!hit) { p.x = nx; p.y = ny; }
      if (dx) p.dir = dx > 0 ? 1 : -1;
      p.animT += dt;
      if (p.animT > 0.18) { p.animT = 0; p.frame ^= 1; }
    } else p.animT = 0;

    // baby wander / sleep
    const b = G.baby;
    if (b.cryT > 0) b.cryT -= dt;
    if (b.state === 'sleep') {
      b.sleepT -= dt;
      if (Math.random() < dt * 2) G.particles.push({ x: b.x + rand(-6, 6), y: b.y - 18, vx: rand(-4, 4), vy: -10, t: 0, life: 1.2, spr: 'sleep' });
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

    // spouse walks to sofa after arriving
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

    // particles & toasts & flash
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
    // floor
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
      const mf = clamp((h - 19.5) / 4.5, 0, 1);
      drawSprite(SPR.moon, WIN.x + WIN.w - 22, WIN.y + 8, 2, false);
      void mf;
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

    // furniture
    drawFurniture(s, h);

    // dirty spots
    for (const d of G ? G.dirty : []) {
      rect(d.x - 5, d.y - 2, 10, 4, '#6e5232');
      rect(d.x - 2, d.y - 4, 4, 3, '#7d5f3b');
    }
  }

  function drawFurniture(s, h) {
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
    rect(90, 199, 18, 12, '#9aa0b0');      // sink
    rect(116, 200, 8, 8, '#191919');       // stove
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
    rect(416, 224, 42, 8, '#f7a8c4');
    // floor lamp
    rect(292, 200, 4, 32, '#9aa0b0');
    rect(286, 188, 16, 12, '#f2d05a');
    if (s.lamp) {
      const g = ctx.createRadialGradient(294, 194, 4, 294, 194, 90);
      g.addColorStop(0, 'rgba(242,208,90,0.35)');
      g.addColorStop(1, 'rgba(242,208,90,0)');
      ctx.fillStyle = g;
      ctx.fillRect(204, 104, 180, 150);
    }
    void h;
  }

  function drawChar(c, sprKey, yOffset) {
    const frames = SPR[sprKey];
    const spr = frames[c.frame & 1];
    const jitter = c.cryT > 0 ? Math.sin(performance.now() / 40) * 1.2 : 0;
    const bob = (c.animT > 0 ? 0 : 0);
    drawSprite(spr, c.x - spr.width * 2 + jitter, c.y - spr.height * 2 + yOffset + bob, 2, c.dir < 0);
  }

  function drawNeedBubble(x, y, n) {
    const bx = Math.round(x - 13), by = Math.round(y - 46);
    rect(bx - 1, by - 1, 28, 24, '#191919');
    rect(bx, by, 26, 22, '#ffffff');
    drawSprite(SPR[NEEDS[n.type].icon], bx + 9, by + 2, 1, false);
    const f = clamp(n.t / n.max, 0, 1);
    rect(bx + 2, by + 16, 22, 4, '#e0e0e0');
    rect(bx + 2, by + 16, 22 * f, 4, f > 0.5 ? '#58d68d' : f > 0.25 ? '#f2d05a' : '#c94f4f');
  }

  function drawHUD(h) {
    rect(0, 0, W, HUD_H, '#14141f');
    rect(0, HUD_H - 1, W, 1, '#2c2c44');
    text('행복도', 6, 7, 1, '#f7f0dc');
    rect(44, 8, 102, 8, '#000');
    rect(45, 9, 100, 6, '#3a3a52');
    const v = clamp(G.happiness, 0, 100);
    const col = v > 50 ? '#58d68d' : v > 25 ? '#f2d05a' : '#c94f4f';
    rect(45, 9, 100 * v / 100, 6, col);
    drawSprite(SPR.heart, 152, 7, 1, false);
    const night = h >= 19 || h < 6;
    drawSprite(night ? SPR.moon : SPR.sun, 232, 7, 1, false);
    text(clockText(h), 244, 7, 1, '#fff');
    text(G.carry ? '운반 중:' : '손: 비었음', 316, 7, 1, '#c9c9d4');
    if (G.carry) drawSprite(SPR[G.carry], 380, 7, 1, false);
    text(stations.find(s => s.item === G.carry)?.label || '', 392, 7, 1, '#f2d05a');
  }

  function drawToasts() {
    let y = H - 14 - G.toasts.length * 14;
    for (const t of G.toasts) {
      const c = textCanvas(t.s, 8, '#fff');
      const w = c.width * 1 + 12;
      rect(W / 2 - w / 2, y - 2, w, 14, 'rgba(10,10,20,0.85)');
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(c, W / 2 - c.width / 2, y, c.width, c.height);
      y += 14;
    }
  }

  function render() {
    ctx.imageSmoothingEnabled = false;
    if (state === 'title') { renderTitle(); return; }
    const h = hour();
    drawRoom(h);

    // entities sorted by y
    const ents = [];
    if (G.spouse.home) ents.push({ y: G.spouse.y, f: () => drawChar(G.spouse, G.role === 'dad' ? 'mom' : 'dad', 0) });
    ents.push({ y: G.baby.y, f: () => drawChar(G.baby, 'baby', 0) });
    ents.push({ y: G.player.y, f: () => drawChar(G.player, G.role, 0) });
    ents.sort((a, b) => a.y - b.y).forEach(e => e.f());

    // carried item above player head
    if (G.carry) drawSprite(SPR[G.carry], G.player.x - 8, G.player.y - 56, 2, false);

    // need bubbles
    for (const n of G.needs) {
      const c = n.who === 'baby' ? G.baby : G.spouse;
      drawNeedBubble(c.x, c.y - 30, n);
    }
    if (G.baby.state === 'sleep') {
      const c = textCanvas('Zzz', 8, '#aee2f5');
      ctx.drawImage(c, G.baby.x + 10 + Math.sin(performance.now() / 300) * 3, G.baby.y - 44, c.width, c.height);
    }

    // particles
    for (const p of G.particles) {
      ctx.globalAlpha = clamp(1 - p.t / p.life, 0, 1);
      drawSprite(SPR[p.spr], p.x - 4, p.y - 4, 1, false);
    }
    ctx.globalAlpha = 1;

    drawHUD(h);
    drawToasts();

    if (G.flash > 0) {
      ctx.fillStyle = `rgba(201,79,79,${G.flash * 0.35})`;
      ctx.fillRect(0, HUD_H, W, H - HUD_H);
    }

    if (state === 'over') renderOver();
    if (state === 'win') renderWin();
  }

  function dim(alpha) { ctx.fillStyle = `rgba(5,5,14,${alpha})`; ctx.fillRect(0, 0, W, H); }

  function renderTitle() {
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(photoPx, 0, 0, W, H);
    ctx.imageSmoothingEnabled = false;
    dim(0.62);
    text('PARENTING', W / 2, 26, 5, '#f2d05a', 'center');
    text('가족의 하루를 지켜라', W / 2, 66, 2, '#fff', 'center');
    const cards = [
      { x: 110, label: '아빠', spr: 'dad' },
      { x: 270, label: '엄마', spr: 'mom' }
    ];
    cards.forEach((c, i) => {
      const on = sel === i;
      rect(c.x, 96, 100, 86, on ? '#f2d05a' : '#3a3a52');
      rect(c.x + 2, 98, 96, 82, on ? '#2c2c1a' : '#191926');
      const spr = SPR[c.spr][0];
      drawSprite(spr, c.x + 50 - spr.width * 2, 102, 2, false);
      text(c.label, c.x + 50, 152, 2, on ? '#f2d05a' : '#c9c9d4', 'center');
      if (on) text('◀ 선택됨 ▶', c.x + 50, 172, 1, '#58d68d', 'center');
    });
    text('← → 또는 A/D: 캐릭터 선택    E: 시작', W / 2, 200, 1, '#fff', 'center');
    text('이동: WASD/방향키   E: 물건 집기/요청 들어주기', W / 2, 216, 1, '#c9c9d4', 'center');
    text('오전 6시~자정까지 가족 행복도를 0 이상 유지! (밤엔 배우자도 찾아와요)', W / 2, 232, 1, '#c9c9d4', 'center');
    text('요청이 밀리면 행복도가 깎여요. 자정까지 살아남으면 승리!', W / 2, 248, 1, '#c9c9d4', 'center');
  }

  function renderOver() {
    dim(0.72);
    text('행복도가 0이 되었어요…', W / 2, 100, 3, '#c94f4f', 'center');
    text('오늘은 여기까지! 내일은 더 잘할 수 있어요.', W / 2, 140, 1, '#fff', 'center');
    text(`성공 ${G.stats.ok} · 실패 ${G.stats.fail}`, W / 2, 164, 1, '#f2d05a', 'center');
    text('R: 다시 도전하기', W / 2, 200, 2, '#58d68d', 'center');
  }

  function renderWin() {
    dim(0.55);
    // the shared family photo, framed
    const maxW = 176, maxH = 104;
    let pw = maxW, ph = maxH;
    if (photo.complete && photo.naturalWidth) {
      const s = Math.min(maxW / photo.naturalWidth, maxH / photo.naturalHeight);
      pw = Math.round(photo.naturalWidth * s);
      ph = Math.round(photo.naturalHeight * s);
    }
    const px = W / 2 - pw / 2, py = 26;
    rect(px - 5, py - 5, pw + 10, ph + 10, '#f2d05a');
    ctx.imageSmoothingEnabled = true;
    if (photo.complete && photo.naturalWidth) ctx.drawImage(photo, px, py, pw, ph);
    else rect(px, py, pw, ph, '#3a3a52');
    ctx.imageSmoothingEnabled = false;
    const ty = py + ph + 14;
    text('오늘 하루도 무사히 이겨낸 거 축하해!', W / 2, ty, 2, '#f2d05a', 'center');
    text('매일의 도전을 더 즐겁게 맞이하자.', W / 2, ty + 26, 2, '#fff', 'center');
    text(`요청 성공 ${G.stats.ok} · 놓친 요청 ${G.stats.fail} · 06:00 → 24:00 생존!`, W / 2, ty + 50, 1, '#c9c9d4', 'center');
    text('R: 내일도 도전하기', W / 2, ty + 70, 2, '#58d68d', 'center');
  }

  // ---------- loop ----------
  window.__PG = { get state() { return state; }, get G() { return G; } };
  let last = 0;
  function frame(ts) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, last ? (ts - last) / 1000 : 0);
    last = ts;
    update(dt);
    render();
  }
  requestAnimationFrame(frame);
})();
