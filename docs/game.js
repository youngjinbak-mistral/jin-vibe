(() => {
  const A = window.ASSETS;
  const W = 480, H = 270, GROUND = H - 8;
  const BOSS_TIME = 300, MEOW_TOTAL = 20;
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
  const SPR = {};
  for (const k in A.sprites) SPR[k] = bake(A.sprites[k], A.palette);
  const OBST = Object.keys(SPR).filter(k => !k.startsWith('boss'));
  const SPINNERS = new Set(['paperclip', 'scissors', 'pencil', 'document', 'sticky_note', 'gpu_chip']);

  const portrait = new Image();
  let portraitPixels = [];
  portrait.onload = () => {
    const c = document.createElement('canvas');
    c.width = portrait.width; c.height = portrait.height;
    const g = c.getContext('2d');
    g.drawImage(portrait, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) {
      const i = (y * c.width + x) * 4;
      if (d[i + 3] > 128) portraitPixels.push({ x, y, c: `rgb(${d[i]},${d[i + 1]},${d[i + 2]})` });
    }
  };
  portrait.src = A.portrait;
  const PW = 32, PH = 40;

  const FONT = A.font;
  function clean(s) {
    return s.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .replace(/[øØ]/g, 'O').replace(/[’‘]/g, "'").replace(/[“”]/g, '"').replace(/[—–]/g, '-')
      .toUpperCase();
  }
  function textW(s, sc) { return s.length * 6 * sc - sc; }
  function text(s, x, y, sc = 1, color = '#fff', align = 'left', shadow = '#000') {
    s = clean(s);
    if (align === 'center') x -= textW(s, sc) / 2;
    else if (align === 'right') x -= textW(s, sc);
    x = Math.round(x); y = Math.round(y);
    const draw = (ox, oy, col) => {
      ctx.fillStyle = col;
      for (let i = 0; i < s.length; i++) {
        const g = FONT[s[i]];
        if (!g) continue;
        for (let r = 0; r < 7; r++) for (let c = 0; c < 5; c++)
          if (g[r][c] === '#') ctx.fillRect(x + ox + (i * 6 + c) * sc, y + oy + r * sc, sc, sc);
      }
    };
    if (shadow) draw(sc, sc, shadow);
    draw(0, 0, color);
  }
  function wrap(s, max) {
    const out = []; let line = '';
    for (const w of clean(s).split(/\s+/)) {
      if ((line + ' ' + w).trim().length > max) { out.push(line); line = w; }
      else line = (line + ' ' + w).trim();
    }
    if (line) out.push(line);
    return out;
  }

  const keys = {};
  let pointer = null;
  const ARROWS = { ArrowLeft: 1, ArrowRight: 1, ArrowUp: 1, ArrowDown: 1, ' ': 1 };
  addEventListener('keydown', e => {
    if (ARROWS[e.key]) e.preventDefault();
    keys[e.key] = true;
    if (e.key === ' ' || e.key === 'Enter') action();
  });
  addEventListener('keyup', e => { keys[e.key] = false; });
  const toWorld = e => {
    const r = cv.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width * W, y: (e.clientY - r.top) / r.height * H };
  };
  cv.addEventListener('pointerdown', e => { pointer = toWorld(e); action(); });
  cv.addEventListener('pointermove', e => { if (pointer) pointer = toWorld(e); });
  addEventListener('pointerup', () => { pointer = null; });

  const rnd = (a, b) => a + Math.random() * (b - a);
  const pick = a => a[Math.floor(Math.random() * a.length)];
  const fmt = t => `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(Math.floor(t % 60)).padStart(2, '0')}`;

  const stars = Array.from({ length: 70 }, () => ({ x: rnd(0, W), y: rnd(0, H * 0.7), s: rnd(0.2, 1), t: rnd(0, 6) }));
  function skyline(n, minH, maxH, wmin, wmax) {
    const b = []; let x = 0;
    while (x < W * 2 + 60) { const w = Math.floor(rnd(wmin, wmax)); b.push({ x, w, h: Math.floor(rnd(minH, maxH)), seed: Math.random() * 1e4 }); x += w + Math.floor(rnd(2, 8)); }
    return { b, len: x };
  }
  const farCity = skyline(0, 40, 110, 18, 40);
  const nearCity = skyline(0, 20, 70, 24, 52);

  const params = new URLSearchParams(location.search);
  let best = +(localStorage.getItem('lifeIsShortBest') || 0);
  let state = 'title';
  let S;

  function reset() {
    S = {
      t: +(params.get('t') || 0), scroll: 0,
      p: { x: 80, y: H / 2, vx: 0, vy: 0, tilt: 0 },
      obs: [], bullets: [], parts: [], stuck: [], trail: [],
      spawnT: 0.8, shake: 0, flash: 0, slow: 1,
      boss: null, bossDone: false, banner: null,
      deadT: 0, quote: null, killer: null,
    };
  }
  reset();

  function action() {
    if (state === 'title') { reset(); state = 'play'; }
    else if (state === 'dead' && S.deadT > 1.6) { reset(); state = 'play'; }
  }

  function spawn() {
    const t = S.t;
    const speed = 95 + Math.min(t, 300) * 0.42;
    const kind = pick(OBST);
    const base = { kind, r: 11, rot: 0, spin: SPINNERS.has(kind) ? rnd(-5, 5) : 0, age: 0 };
    const roll = Math.random();
    const p = S.p;
    if (t > 60 && roll < 0.12) {
      const gap = rnd(40, H - 60);
      for (let y = 16; y < H - 10; y += 30) if (Math.abs(y - gap) > 34)
        S.obs.push({ ...base, kind: pick(OBST), x: W + 20, y, vx: -speed * 0.8, vy: 0 });
    } else if (roll < 0.45) {
      S.obs.push({ ...base, x: W + 20, y: rnd(14, H - 14), vx: -speed * rnd(0.8, 1.2), vy: 0 });
    } else if (roll < 0.62) {
      S.obs.push({ ...base, x: W + 20, y: rnd(40, H - 40), vx: -speed * 0.9, vy: 0, sine: rnd(30, 60), sf: rnd(2, 4), y0: 0 });
    } else if (roll < 0.82) {
      const edge = pick(['r', 't', 'b']);
      const x = edge === 'r' ? W + 20 : rnd(p.x + 40, W);
      const y = edge === 't' ? -20 : edge === 'b' ? H + 20 : rnd(10, H - 10);
      const a = Math.atan2(p.y - y, p.x - x);
      const sp = speed * 1.05;
      S.obs.push({ ...base, x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, spin: rnd(-6, 6) });
    } else {
      S.obs.push({ ...base, x: rnd(p.x - 20, W - 20), y: -20, vx: -speed * 0.35, vy: rnd(20, 60), g: 160 });
    }
  }

  function startBoss() {
    S.boss = { x: W + 80, y: H / 2, tx: W - 70, shouts: 0, timer: 2.4, mouth: 0, bubble: 0, phase: 'enter', t: 0, rot: 0, vy: 0, hungerT: 0, alpha: 1 };
  }

  function shout() {
    const b = S.boss;
    b.shouts++;
    b.mouth = 0.6; b.bubble = 0.9; S.shake = Math.max(S.shake, 4);
    const n = b.shouts;
    const sp = 110 + n * 6;
    const word = 'MEOW!';
    const mx = b.x - 30, my = b.y + 14;
    const p = S.p;
    const pattern = (n - 1) % 4;
    const add = (vx, vy, ch, delay = 0) => S.bullets.push({ x: mx, y: my, vx, vy, ch, delay, r: 6, age: 0 });
    if (pattern === 0) {
      const a = Math.atan2(p.y - my, p.x - mx);
      [...word].forEach((ch, i) => add(Math.cos(a) * sp, Math.sin(a) * sp, ch, i * 0.09));
    } else if (pattern === 1) {
      const a0 = Math.atan2(p.y - my, p.x - mx);
      for (let k = 0; k < 2; k++) [...word].forEach((ch, i) => {
        const a = a0 + (i - 2) * 0.28 + (k ? 0.14 : 0);
        add(Math.cos(a) * sp, Math.sin(a) * sp, ch, k * 0.35);
      });
    } else if (pattern === 2) {
      const m = 10 + Math.floor(n / 4) * 2;
      for (let i = 0; i < m; i++) {
        const a = Math.PI / 2 + (i / (m - 1)) * Math.PI;
        add(Math.cos(a) * sp * 0.8, Math.sin(a) * sp * 0.8, word[i % word.length]);
      }
    } else {
      for (let k = 0; k < 3; k++) [...word].forEach((ch, i) => {
        S.bullets.push({ x: mx, y: my, vx: -sp * 0.9, vy: 0, ch, delay: k * 0.25 + i * 0.07, r: 6, age: 0, sine: 40 + k * 15, sf: 3 + k, y0: my + (k - 1) * 50 });
      });
    }
  }

  function die(killer) {
    state = 'dead';
    S.deadT = 0;
    S.killer = killer;
    S.quote = pick(A.quotes);
    S.shake = 14; S.flash = 0.18; S.slow = 0.25;
    const p = S.p;
    const ix = killer ? killer.x : p.x + 20, iy = killer ? killer.y : p.y;
    for (const px of portraitPixels) {
      const x = p.x - PW / 2 + px.x, y = p.y - PH / 2 + px.y;
      const a = Math.atan2(y - iy, x - ix) + rnd(-0.6, 0.6);
      const s = rnd(60, 260);
      S.parts.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s - rnd(40, 160), c: px.c, sz: 1, g: 420, life: 99, bounce: 0.35 });
    }
    for (let i = 0; i < 160; i++) {
      const a = rnd(0, Math.PI * 2), s = rnd(40, 320);
      S.parts.push({ x: p.x + rnd(-6, 6), y: p.y + rnd(-10, 10), vx: Math.cos(a) * s, vy: Math.sin(a) * s - 120, c: pick(['#b01e3c', '#ff4757', '#7a0d1f', '#d62839']), sz: pick([1, 1, 2, 2, 3]), g: 520, life: 99, blood: true });
    }
    if (S.t > best) { best = S.t; localStorage.setItem('lifeIsShortBest', String(best)); }
  }

  function hitPlayer(x, y, r) {
    const p = S.p, hw = 9, hh = 15;
    const cx = Math.max(p.x - hw, Math.min(x, p.x + hw));
    const cy = Math.max(p.y - hh + 2, Math.min(y, p.y + hh + 2));
    return (x - cx) ** 2 + (y - cy) ** 2 < r * r;
  }

  function updateParts(dt) {
    for (const q of S.parts) {
      q.vy += (q.g || 0) * dt;
      q.x += q.vx * dt; q.y += q.vy * dt;
      q.life -= dt;
      if (q.y > GROUND) {
        q.y = GROUND;
        if (q.blood) { q.dead = true; if (S.stuck.length < 900) S.stuck.push({ x: q.x, y: GROUND + rnd(0, 3), c: q.c, w: q.sz + Math.floor(rnd(1, 4)) }); }
        else { q.vy *= -(q.bounce || 0); q.vx *= 0.6; if (Math.abs(q.vy) < 20) { q.vy = 0; q.g = 0; q.vx *= 0.8; } }
      }
      if (q.x < -10 || q.x > W + 10 || q.life <= 0) q.dead = true;
    }
    S.parts = S.parts.filter(q => !q.dead);
  }

  function update(dt) {
    S.shake = Math.max(0, S.shake - dt * 30);
    S.flash = Math.max(0, S.flash - dt);
    if (state === 'title') { S.scroll += dt * 40; return; }
    if (state === 'dead') {
      S.deadT += dt;
      S.slow = Math.min(1, S.slow + dt * 0.8);
      const sdt = dt * S.slow;
      updateParts(sdt);
      for (const o of S.obs) if (o !== S.killer) { o.x += o.vx * sdt * 0.3; o.y += o.vy * sdt * 0.3; }
      for (const b of S.bullets) { b.x += b.vx * sdt * 0.3; b.y += b.vy * sdt * 0.3; }
      return;
    }

    S.t += dt;
    const p = S.p;
    S.scroll += dt * (60 + Math.min(S.t, 300) * 0.2);

    let ax = 0, ay = 0;
    if (keys.ArrowLeft || keys.a) ax -= 1;
    if (keys.ArrowRight || keys.d) ax += 1;
    if (keys.ArrowUp || keys.w) ay -= 1;
    if (keys.ArrowDown || keys.s) ay += 1;
    const SPD = 165;
    if (pointer && !ax && !ay) {
      const dx = pointer.x - p.x, dy = pointer.y - p.y, d = Math.hypot(dx, dy);
      if (d > 3) { ax = dx / d; ay = dy / d; }
    } else if (ax && ay) { ax *= Math.SQRT1_2; ay *= Math.SQRT1_2; }
    p.vx += (ax * SPD - p.vx) * Math.min(1, dt * 14);
    p.vy += (ay * SPD - p.vy) * Math.min(1, dt * 14);
    p.x = Math.max(PW / 2, Math.min(W - PW / 2, p.x + p.vx * dt));
    p.y = Math.max(PH / 2, Math.min(GROUND - PH / 2 + 4, p.y + p.vy * dt));
    p.tilt += ((p.vx / SPD) * 0.18 - p.tilt) * Math.min(1, dt * 10);
    if (Math.hypot(p.vx, p.vy) > 40 && Math.random() < 0.6)
      S.parts.push({ x: p.x - 10 + rnd(-3, 3), y: p.y + 14 + rnd(-3, 3), vx: -40 - p.vx * 0.2, vy: rnd(-10, 10), c: pick(['#ffd166', '#ffafcc', '#4cc9f0', '#80ed99']), sz: 1, life: 0.5 });

    if (!S.boss && !S.bossDone && S.t >= BOSS_TIME) startBoss();
    if (!S.boss) {
      S.spawnT -= dt;
      if (S.spawnT <= 0) {
        spawn();
        const rate = Math.max(0.26, 0.85 - Math.min(S.t, 300) * 0.002);
        S.spawnT = rate * rnd(0.7, 1.3) * (S.bossDone ? 0.85 : 1);
      }
    }

    for (const o of S.obs) {
      o.age += dt;
      if (o.g) o.vy += o.g * dt;
      o.x += o.vx * dt;
      if (o.sine) { o.y0 = o.y0 || o.y; o.y = o.y0 + Math.sin(o.age * o.sf) * o.sine; } else o.y += o.vy * dt;
      o.rot += o.spin * dt;
      if (o.x < -40 || o.x > W + 60 || o.y > H + 40 || o.y < -60) o.dead = true;
      if (hitPlayer(o.x, o.y, o.r)) { die(o); return; }
    }
    S.obs = S.obs.filter(o => !o.dead);

    for (const b of S.bullets) {
      if (b.delay > 0) { b.delay -= dt; continue; }
      b.age += dt;
      b.x += b.vx * dt;
      if (b.sine) b.y = b.y0 + Math.sin(b.age * b.sf) * b.sine; else b.y += b.vy * dt;
      if (b.x < -20 || b.x > W + 20 || b.y < -20 || b.y > H + 20) b.dead = true;
      if (hitPlayer(b.x, b.y, b.r)) { die(b); return; }
    }
    S.bullets = S.bullets.filter(b => !b.dead);

    const B = S.boss;
    if (B) {
      B.t += dt;
      B.mouth = Math.max(0, B.mouth - dt);
      B.bubble = Math.max(0, B.bubble - dt);
      if (B.phase === 'enter') {
        B.x += (B.tx - B.x) * Math.min(1, dt * 1.5);
        if (Math.abs(B.x - B.tx) < 2) B.phase = 'fight';
      } else if (B.phase === 'fight') {
        B.y = H / 2 + Math.sin(B.t * 0.9) * 70;
        B.x = B.tx + Math.sin(B.t * 1.7) * 10;
        B.timer -= dt;
        if (B.timer <= 0) {
          if (B.shouts < MEOW_TOTAL) { shout(); B.timer = Math.max(1.5, 2.5 - B.shouts * 0.04); }
          else if (!S.bullets.length) { B.phase = 'hungry'; B.hungerT = 3.6; }
        }
      } else if (B.phase === 'hungry') {
        B.y += (H / 2 - B.y) * Math.min(1, dt * 2);
        B.hungerT -= dt;
        if (B.hungerT <= 0) {
          B.phase = 'dying'; B.vy = -120; S.shake = 10; S.flash = 0.12;
          for (let i = 0; i < 120; i++) {
            const a = rnd(0, Math.PI * 2), s = rnd(40, 220);
            S.parts.push({ x: B.x + rnd(-30, 30), y: B.y + rnd(-30, 30), vx: Math.cos(a) * s, vy: Math.sin(a) * s, c: pick(['#240046', '#7b2cbf', '#ff4757', '#ffd166']), sz: pick([1, 2, 2]), g: 300, life: 2 });
          }
        }
      } else if (B.phase === 'dying') {
        B.vy += 400 * dt; B.y += B.vy * dt; B.rot += dt * 3; B.alpha = Math.max(0, B.alpha - dt * 0.6);
        if (B.y > H + 80) {
          S.boss = null; S.bossDone = true;
          S.banner = { t: 5, q: pick(A.quotes) };
        }
      }
      if (B && B.phase !== 'dying' && hitPlayer(B.x, B.y, 38)) { die(B); return; }
    }
    if (S.banner) { S.banner.t -= dt; if (S.banner.t <= 0) S.banner = null; }
    updateParts(dt);
  }

  function drawBg() {
    const g = ctx.createLinearGradient(0, 0, 0, H);
    const danger = S.boss ? 1 : 0;
    g.addColorStop(0, danger ? '#2a0612' : '#140a2e');
    g.addColorStop(0.6, danger ? '#4a0b2a' : '#2b1257');
    g.addColorStop(1, danger ? '#7a1430' : '#5a2a7a');
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    const now = performance.now() / 1000;
    for (const s of stars) {
      const x = ((s.x - S.scroll * s.s * 0.1) % W + W) % W;
      ctx.fillStyle = Math.sin(now * 3 + s.t) > 0.6 ? '#fff' : '#a89cc8';
      ctx.fillRect(Math.floor(x), Math.floor(s.y), 1, 1);
    }
    ctx.fillStyle = danger ? '#ff4757' : '#ffd166';
    ctx.fillRect(400, 30, 18, 18);
    ctx.fillStyle = danger ? '#2a0612' : '#140a2e';
    ctx.fillRect(406, 28, 14, 14);
    const city = (c, speed, col, win) => {
      const off = (S.scroll * speed) % c.len;
      for (const b of c.b) {
        let x = Math.floor(b.x - off);
        if (x + b.w < 0) x += c.len;
        if (x > W) continue;
        ctx.fillStyle = col;
        ctx.fillRect(x, GROUND - b.h, b.w, b.h);
        if (win) for (let wy = GROUND - b.h + 4; wy < GROUND - 4; wy += 6)
          for (let wx = x + 3; wx < x + b.w - 3; wx += 5) {
            const v = Math.sin(b.seed + wx * 13.1 + wy * 7.7);
            if (v > 0.35) { ctx.fillStyle = v > 0.8 ? '#ffd166' : win; ctx.fillRect(wx, wy, 2, 2); }
          }
      }
    };
    city(farCity, 0.2, danger ? '#3a0a1e' : '#24134a', null);
    city(nearCity, 0.5, danger ? '#22050f' : '#170b30', danger ? '#ff475755' : '#7b2cbf88');
    ctx.fillStyle = '#0d0820'; ctx.fillRect(0, GROUND, W, H - GROUND);
    ctx.fillStyle = danger ? '#ff4757' : '#7b2cbf';
    for (let x = -((S.scroll * 1.2) % 16); x < W; x += 16) ctx.fillRect(Math.floor(x), GROUND, 8, 1);
  }

  function drawSprite(img, x, y, sc, rot = 0, alpha = 1) {
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.translate(Math.round(x), Math.round(y));
    if (rot) ctx.rotate(rot);
    ctx.drawImage(img, -img.width * sc / 2, -img.height * sc / 2, img.width * sc, img.height * sc);
    ctx.restore();
  }

  function drawPlayer() {
    const p = S.p;
    const bob = Math.sin(performance.now() / 120) * (Math.hypot(p.vx, p.vy) > 20 ? 1 : 0.5);
    ctx.fillStyle = '#00000055';
    ctx.fillRect(Math.round(p.x - 10), GROUND - 1, 20, 2);
    ctx.fillStyle = '#ffafcc33';
    ctx.beginPath(); ctx.arc(p.x, p.y, 22, 0, Math.PI * 2); ctx.fill();
    if (portrait.complete) drawSprite(portrait, p.x, p.y + bob, 1, p.tilt);
  }

  function drawBullet(b) {
    if (b.delay > 0) return;
    const pulse = Math.floor(performance.now() / 100) % 2;
    text(b.ch, b.x - 5, b.y - 7, 2, pulse ? '#ff4757' : '#ffafcc', 'left', '#240046');
  }

  function drawBoss() {
    const B = S.boss;
    const shake = B.mouth > 0 ? rnd(-2, 2) : 0;
    const img = B.mouth > 0 || B.phase === 'hungry' && Math.floor(B.t * 4) % 2 ? SPR.boss_cat : SPR.boss_cat_closed;
    ctx.save();
    ctx.globalAlpha = 0.25 * B.alpha;
    ctx.fillStyle = '#ff4757';
    ctx.beginPath(); ctx.arc(B.x, B.y, 54 + Math.sin(B.t * 6) * 3, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
    drawSprite(img, B.x + shake, B.y + shake, 3, B.rot, B.alpha);
    if (B.bubble > 0) bubble(B.x - 20, B.y - 62, ['MEOW!'], 3, '#ff4757');
    if (B.phase === 'hungry') bubble(Math.min(B.x - 40, W - 130), B.y - 66, ['OH I AM TOO HUNGRY', 'TO MEOW MORE.'], 1, '#240046');
  }

  function bubble(cx, y, lines, sc, col) {
    const w = Math.max(...lines.map(l => textW(l, sc))) + 12;
    const h = lines.length * 9 * sc + 8;
    let x = Math.round(Math.max(4, Math.min(W - w - 4, cx - w / 2)));
    y = Math.round(Math.max(4, y - h / 2));
    ctx.fillStyle = '#240046'; ctx.fillRect(x - 1, y - 1, w + 2, h + 2);
    ctx.fillStyle = '#fff3b0'; ctx.fillRect(x, y, w, h);
    ctx.fillStyle = '#fff3b0'; ctx.fillRect(Math.round(cx), y + h, 6, 4);
    lines.forEach((l, i) => text(l, x + 6, y + 5 + i * 9 * sc, sc, col, 'left', null));
  }

  function panel(x, y, w, h) {
    ctx.fillStyle = '#0b0b16dd'; ctx.fillRect(x, y, w, h);
    ctx.fillStyle = '#7b2cbf'; ctx.fillRect(x, y, w, 1); ctx.fillRect(x, y + h - 1, w, 1); ctx.fillRect(x, y, 1, h); ctx.fillRect(x + w - 1, y, 1, h);
    ctx.fillStyle = '#ffafcc'; ctx.fillRect(x + 2, y + 2, 2, 2); ctx.fillRect(x + w - 4, y + 2, 2, 2); ctx.fillRect(x + 2, y + h - 4, 2, 2); ctx.fillRect(x + w - 4, y + h - 4, 2, 2);
  }

  function drawQuote(q, y, color) {
    const lines = wrap(q.q, 60);
    lines.forEach((l, i) => text(l, W / 2, y + i * 10, 1, color, 'center'));
    text('- ' + q.a, W / 2, y + lines.length * 10 + 6, 1, '#ffd166', 'center');
    return y + lines.length * 10 + 16;
  }

  function drawHUD() {
    text('TIME ' + fmt(S.t), 8, 8, 1, '#fff3b0');
    text('BEST ' + fmt(best), W - 8, 8, 1, '#ffafcc', 'right');
    if (!S.boss && !S.bossDone && S.t > BOSS_TIME - 6 && Math.floor(S.t * 4) % 2)
      text('WARNING: SOMETHING HUNGRY APPROACHES', W / 2, 40, 1, '#ff4757', 'center');
    if (S.boss) {
      const n = S.boss.shouts;
      text(`MEOWS ${n}/${MEOW_TOTAL}`, W / 2, 8, 1, '#ff4757', 'center');
      ctx.fillStyle = '#240046'; ctx.fillRect(W / 2 - 60, 18, 120, 4);
      ctx.fillStyle = '#ff4757'; ctx.fillRect(W / 2 - 60, 18, 120 * (1 - n / MEOW_TOTAL), 4);
    }
    if (S.banner) {
      panel(40, 50, W - 80, 90);
      text('THE CAT STARVED. YOU SURVIVED.', W / 2, 60, 1, '#80ed99', 'center');
      drawQuote(S.banner.q, 80, '#fff');
    }
  }

  function drawTitle() {
    panel(60, 26, W - 120, 210);
    text('LIFE IS SHORT', W / 2 + 1, 40, 4, '#ff4757', 'center', '#240046');
    text('A TINY PIXEL DODGER', W / 2, 74, 1, '#ffd166', 'center');
    if (portrait.complete) drawSprite(portrait, W / 2, 112 + Math.sin(performance.now() / 300) * 2, 1);
    const ex = ['stapler', 'document', 'robot', 'coffee_mug', 'gpu_chip', 'folder'];
    ex.forEach((k, i) => drawSprite(SPR[k], 100 + i * 56, 160, 2, Math.sin(performance.now() / 400 + i) * 0.2));
    text('ARROW KEYS TO MOVE. KEEP MOVING.', W / 2, 186, 1, '#fff', 'center');
    text('DODGE THE OFFICE. DODGE THE AI. SURVIVE 5 MIN...', W / 2, 198, 1, '#a89cc8', 'center');
    if (Math.floor(performance.now() / 500) % 2) text('PRESS SPACE OR TAP TO START', W / 2, 216, 1, '#80ed99', 'center');
  }

  function drawDead() {
    for (const s of S.stuck) { ctx.fillStyle = s.c; ctx.fillRect(Math.round(s.x), Math.round(s.y), s.w, 1); }
    if (S.deadT < 1.4) return;
    const a = Math.min(1, (S.deadT - 1.4) * 2);
    ctx.globalAlpha = a;
    panel(30, 30, W - 60, 200);
    text('YOU DIED', W / 2, 44, 4, '#ff4757', 'center', '#240046');
    for (let i = 0; i < 6; i++) {
      const dx = W / 2 - 80 + i * 31, len = ((i * 7) % 5 + 2) * Math.min(1, S.deadT - 1.4) * 3;
      ctx.fillStyle = '#b01e3c'; ctx.fillRect(dx, 72, 2, len);
    }
    text('YOU LASTED ' + fmt(S.t) + (S.t >= best && S.t > 0 ? '  NEW BEST!' : '  BEST ' + fmt(best)), W / 2, 92, 1, '#fff3b0', 'center');
    const y = drawQuote(S.quote, 116, '#fff');
    if (S.deadT > 1.6 && Math.floor(performance.now() / 500) % 2)
      text('PRESS SPACE TO LIVE AGAIN. USE IT WELL.', W / 2, Math.max(y + 10, 206), 1, '#80ed99', 'center');
    ctx.globalAlpha = 1;
  }

  function render() {
    ctx.imageSmoothingEnabled = false;
    ctx.save();
    if (S.shake) ctx.translate(Math.round(rnd(-S.shake, S.shake)), Math.round(rnd(-S.shake, S.shake)));
    drawBg();
    if (state === 'title') { ctx.restore(); drawTitle(); return; }
    for (const o of S.obs) drawSprite(SPR[o.kind], o.x, o.y, 2, o.rot);
    if (S.boss) drawBoss();
    for (const b of S.bullets) drawBullet(b);
    if (state === 'play') drawPlayer();
    for (const q of S.parts) {
      ctx.globalAlpha = q.life < 0.5 ? Math.max(0, q.life * 2) : 1;
      ctx.fillStyle = q.c; ctx.fillRect(Math.round(q.x), Math.round(q.y), q.sz, q.sz);
    }
    ctx.globalAlpha = 1;
    ctx.restore();
    if (state === 'dead') drawDead();
    else drawHUD();
    if (S.flash > 0) { ctx.fillStyle = `rgba(255,255,255,${Math.min(1, S.flash * 6)})`; ctx.fillRect(0, 0, W, H); }
    ctx.fillStyle = '#00000022';
    for (let y = 0; y < H; y += 2) ctx.fillRect(0, y, W, 1);
  }

  let last = performance.now();
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    update(dt);
    render();
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
