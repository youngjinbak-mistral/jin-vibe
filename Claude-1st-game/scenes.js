const SCENES = [
  { name: 'OPEN OFFICE', draw(ctx, W, H, GROUND, scroll, t) {
    ctx.fillStyle = '#1a1535'; ctx.fillRect(0, 0, W, H);
    let f = scroll * 0.2;
    for (let i = 0; i < 4; i++) { ctx.fillStyle = '#241a45'; ctx.fillRect(((i*120 - f % 120) | 0), 40, 100, 180); }
    ctx.fillStyle = '#15102a'; ctx.fillRect(0, 40, W, 8);
    for (let i = 0; i < 10; i++) {
      let x = ((i*100 - f * 1.5) % 100 + 100) % 100;
      let tw = Math.sin(t*2 + i) > 0 ? 1 : 0;
      ctx.fillStyle = tw ? '#ffaa55' : '#553388';
      ctx.fillRect((x*4.8)|0, 50, 4, 4);
    }
    ctx.fillStyle = '#101020'; ctx.fillRect(0, 220, W, 50);
    ctx.fillStyle = '#2a2050'; ctx.fillRect(0, GROUND, W, H - GROUND);
    let m = scroll * 0.6;
    for (let x = -(m % 120); x < W; x += 120) {
      ctx.fillStyle = '#3a2a55'; ctx.fillRect(x+10, GROUND-22, 100, 6);
      ctx.fillStyle = '#1a1530'; ctx.fillRect(x+20, GROUND-40, 20, 18);
      ctx.fillRect(x+70, GROUND-40, 20, 18);
      let on = (Math.sin(t*3 + x*0.1) > -0.5) ? 1 : 0;
      ctx.fillStyle = on ? '#55ccff' : '#152540';
      ctx.fillRect(x+22, GROUND-38, 16, 10);
      ctx.fillRect(x+72, GROUND-38, 16, 10);
      ctx.fillStyle = '#553388'; ctx.fillRect(x+48, GROUND-30, 4, 10);
      ctx.fillStyle = '#33aa77'; ctx.fillRect(x+2, GROUND-10, 8, 10);
    }
  } },
  { name: 'TOILET', draw(ctx, W, H, GROUND, scroll, t) {
    ctx.fillStyle = '#2a2030'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#443344'; ctx.fillRect(0, 0, W, 120);
    ctx.fillStyle = '#554455'; ctx.fillRect(0, 120, W, 2);
    ctx.fillStyle = '#332233'; ctx.fillRect(0, 122, W, 140);
    for (let i = 0; i < 10; i++) { ctx.fillStyle = (i%2) ? '#2a2030' : '#332233'; ctx.fillRect(i*48, 0, 24, 120); }
    let f = scroll * 0.6;
    for (let x = -(f % 80); x < W; x += 80) {
      ctx.fillStyle = '#1a1520'; ctx.fillRect(x+4, 130, 72, 132);
      ctx.fillStyle = '#3a2a3a'; ctx.fillRect(x+8, 135, 64, 50);
      ctx.fillStyle = '#111'; ctx.fillRect(x+28, 145, 20, 20);
      ctx.fillStyle = '#ffcc55'; ctx.fillRect(x+36, 153, 4, 4);
    }
    ctx.fillStyle = '#1a1520'; ctx.fillRect(0, GROUND, W, H - GROUND);
    ctx.fillStyle = '#222'; ctx.fillRect(0, 200, W, 10);
  } },
  { name: 'OUTSIDE BUILDING', draw(ctx, W, H, GROUND, scroll, t) {
    let sky = ctx.createLinearGradient(0, 0, 0, 100); sky.addColorStop(0, '#1a1a40'); sky.addColorStop(1, '#4a2a5a');
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, 100);
    let f = scroll * 0.2;
    for (let i = 0; i < 8; i++) {
      let x = ((i*70 - f) % 350 + 350) % 350 - 70;
      ctx.fillStyle = '#251535'; ctx.fillRect(x|0, 50, 60, 170);
      ctx.fillStyle = '#553388'; for(let j=0; j<4; j++) for(let k=0; k<5; k++) if((i+j+k)%3) ctx.fillRect(x+8+j*12, 60+k*20, 8, 10);
    }
    ctx.fillStyle = '#151525'; ctx.fillRect(0, 200, W, 70);
    ctx.fillStyle = '#221530'; ctx.fillRect(0, 210, W, 60);
    let m = scroll * 0.6;
    for (let x = -(m % 60); x < W; x += 60) {
      ctx.fillStyle = '#444'; ctx.fillRect(x, 210, 4, 60);
      if(Math.sin(t*2 + x) > 0) { ctx.fillStyle = '#ffaa55'; ctx.fillRect(x-4, 215, 4, 4); ctx.fillRect(x+4, 215, 4, 4); }
    }
    ctx.fillStyle = '#111'; ctx.fillRect(0, GROUND, W, H - GROUND);
  } },
  { name: 'LOBBY', draw(ctx, W, H, GROUND, scroll, t) {
    ctx.fillStyle = '#1a1525'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#2a2040'; ctx.fillRect(0, 0, W, 100);
    let f = scroll * 0.3;
    for (let x = -(f % 40); x < W; x += 40) {
      ctx.fillStyle = '#15102a'; ctx.fillRect(x+2, 20, 36, 60);
      ctx.fillStyle = '#5533aa'; ctx.fillRect(x+4, 22, 32, 56);
    }
    ctx.fillStyle = '#554488'; ctx.fillRect(0, 80, W, 30);
    ctx.fillStyle = '#332255'; ctx.fillRect(0, 110, W, 150);
    ctx.fillStyle = '#221530'; ctx.fillRect(0, GROUND, W, H - GROUND);
    ctx.fillStyle = '#445566'; ctx.fillRect(0, GROUND-5, W, 5);
    ctx.fillStyle = '#334455'; ctx.fillRect(W/2-40, GROUND-20, 80, 15);
    ctx.fillStyle = '#ffaa55'; ctx.fillRect(W/2-30, GROUND-15, 60, 4);
  } },
  { name: 'CANTEEN', draw(ctx, W, H, GROUND, scroll, t) {
    ctx.fillStyle = '#221525'; ctx.fillRect(0, 0, W, H);
    let f = scroll * 0.2;
    for (let x = -(f % 100); x < W; x += 100) {
      ctx.fillStyle = '#3a2a3a'; ctx.fillRect(x+10, 10, 80, 50);
      ctx.fillStyle = '#ffcc55'; for(let j=0;j<3;j++) if((Math.sin(t*2 + x + j) > 0)) ctx.fillRect(x+20+j*20, 20, 12, 12);
    }
    ctx.fillStyle = '#443322'; ctx.fillRect(0, 70, W, 190);
    ctx.fillStyle = '#151525'; ctx.fillRect(0, GROUND, W, H - GROUND);
    let m = scroll * 0.6;
    for (let x = -(m % 90); x < W; x += 90) {
      ctx.fillStyle = '#5a4a3a'; ctx.fillRect(x+5, GROUND-25, 80, 5);
      ctx.fillStyle = '#3a2a2a'; ctx.fillRect(x+15, GROUND-20, 60, 15);
      ctx.fillStyle = '#cc7788'; ctx.fillRect(x+20, GROUND-18, 10, 10);
    }
  } },
  { name: 'MEETING ROOM', draw(ctx, W, H, GROUND, scroll, t) {
    ctx.fillStyle = '#1a1a30'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#2a2a45'; ctx.fillRect(0, 0, W, 150);
    ctx.fillStyle = '#334455'; ctx.fillRect(0, 150, W, 120);
    ctx.fillStyle = '#151525'; ctx.fillRect(0, GROUND, W, H - GROUND);
    ctx.fillStyle = '#554433'; ctx.fillRect(40, GROUND-10, W-80, 8);
    let f = scroll * 0.2;
    for (let x = -(f % 60); x < W; x += 60) {
      ctx.fillStyle = '#443322'; ctx.fillRect(x, GROUND-12, 30, 8);
    }
    ctx.fillStyle = '#eeeeff'; ctx.fillRect(W/2-60, 20, 120, 80);
    ctx.fillStyle = '#3355aa'; ctx.fillRect(W/2-50, 80, 100, 15);
    ctx.fillStyle = '#cc5555'; ctx.fillRect(W/2-50, 60, 40, 20);
    if (Math.sin(t*4) > 0.5) { ctx.fillStyle = '#ffff88'; ctx.fillRect(W/2-10, GROUND-15, 20, 10); }
  } },
  { name: 'SERVER ROOM', draw(ctx, W, H, GROUND, scroll, t) {
    ctx.fillStyle = '#101515'; ctx.fillRect(0, 0, W, H);
    let m = scroll * 0.6;
    for (let x = -(m % 100); x < W; x += 100) {
      ctx.fillStyle = '#1a2020'; ctx.fillRect(x, 10, 90, 240);
      ctx.fillStyle = '#0a1010'; ctx.fillRect(x+4, 14, 82, 232);
      for(let j=0; j<12; j++) {
        ctx.fillStyle = '#222'; ctx.fillRect(x+8, 20+j*18, 74, 14);
        let c = (Math.sin(t*5 + x + j*3) > 0.5) ? '#33ff66' : '#113311';
        ctx.fillStyle = c; ctx.fillRect(x+12, 24+j*18, 4, 4); ctx.fillRect(x+20, 24+j*18, 4, 4);
        ctx.fillStyle = (Math.sin(t*3 + x + j) > 0.8) ? '#ffaa55' : '#331100';
        ctx.fillRect(x+70, 24+j*18, 4, 4);
      }
    }
    ctx.fillStyle = '#151520'; ctx.fillRect(0, GROUND, W, H - GROUND);
    ctx.fillStyle = '#1a2030'; for(let i=0;i<6;i++) ctx.fillRect(i*80, 250, 60, 3);
  } },
  { name: 'ELEVATOR', draw(ctx, W, H, GROUND, scroll, t) {
    ctx.fillStyle = '#2a2a3a'; ctx.fillRect(0, 0, W, H);
    let f = scroll * 0.1;
    for (let x = -(f % 30); x < W; x += 30) {
      ctx.fillStyle = '#333345'; ctx.fillRect(x, 0, 15, H);
      ctx.fillStyle = '#222230'; ctx.fillRect(x+15, 0, 15, H);
    }
    ctx.fillStyle = '#15151a'; ctx.fillRect(0, 0, W, 5); ctx.fillRect(0, H-10, W, 10);
    ctx.fillStyle = '#225588'; ctx.fillRect(10, 15, 40, 12);
    ctx.fillStyle = '#88aaff'; if(Math.sin(t*2) > 0) ctx.fillRect(14, 19, 32, 4);
    ctx.fillStyle = '#151525'; ctx.fillRect(0, GROUND, W, H - GROUND);
    for(let i=0; i<4; i++) { let c = (Math.sin(t*2 + i*1.5) > 0.5) ? '#ffcc55' : '#554422'; ctx.fillStyle = c; ctx.fillRect(150 + i*15, 30, 10, 10); }
  } },
  { name: 'ROOFTOP', draw(ctx, W, H, GROUND, scroll, t) {
    let sky = ctx.createLinearGradient(0,0,0,200); sky.addColorStop(0, '#050515'); sky.addColorStop(1, '#1a1535');
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, 200);
    for(let i=0; i<30; i++) { let x=(i*17+t*5)%W; let y=(i*13)%150; let a=(Math.sin(t*2+i)>0)?1:0.5; ctx.fillStyle = `rgba(255,255,255,${a})`; ctx.fillRect(x|0, y|0, 1, 1); }
    let f = scroll * 0.2;
    for (let i = 0; i < 6; i++) {
      let x = ((i*80 - f) % 400 + 400) % 400 - 80;
      ctx.fillStyle = '#0a0a18'; ctx.fillRect(x|0, 120, 70, 100);
      ctx.fillStyle = '#332255'; for(let j=0;j<3;j++) for(let k=0;k<4;k++) if((i+j+k)%4) ctx.fillRect(x+10+j*20, 130+k*20, 10, 10);
    }
    ctx.fillStyle = '#1a1525'; ctx.fillRect(0, 210, W, 60);
    ctx.fillStyle = '#10101a'; ctx.fillRect(0, GROUND, W, H - GROUND);
    let m = scroll * 0.6;
    for (let x = -(m % 60); x < W; x += 60) {
      ctx.fillStyle = '#333'; ctx.fillRect(x+10, 170, 20, 40);
      ctx.fillStyle = '#222'; ctx.fillRect(x+35, 160, 2, 50);
      ctx.fillStyle = '#ff3333'; if(Math.sin(t*3+x)>0) ctx.fillRect(x+35, 158, 2, 2);
    }
  } },
  { name: 'BREAK ROOM', draw(ctx, W, H, GROUND, scroll, t) {
    ctx.fillStyle = '#1a1525'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#2a2050'; ctx.fillRect(0, 0, W, 120);
    let f = scroll * 0.6;
    for (let x = -(f % 150); x < W; x += 150) {
      ctx.fillStyle = '#332244'; ctx.fillRect(x, 40, 50, 180);
      ctx.fillStyle = '#1155aa'; ctx.fillRect(x+5, 45, 40, 60);
      ctx.fillStyle = '#aa3344'; ctx.fillRect(x+5, 110, 40, 40);
      if(Math.sin(t*3+x)>0) { ctx.fillStyle = '#ffcc55'; ctx.fillRect(x+20, 180, 10, 10); }
    }
    ctx.fillStyle = '#221535'; ctx.fillRect(0, 120, W, 140);
    ctx.fillStyle = '#151525'; ctx.fillRect(0, GROUND, W, H - GROUND);
    for (let x = -(f % 200); x < W; x += 200) {
      ctx.fillStyle = '#445566'; ctx.fillRect(x+60, GROUND-15, 80, 5);
      ctx.fillStyle = '#334455'; ctx.fillRect(x+70, GROUND-10, 60, 8);
    }
  } },
  { name: 'PARKING GARAGE', draw(ctx, W, H, GROUND, scroll, t) {
    ctx.fillStyle = '#1a1a1a'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#151515'; ctx.fillRect(0, 100, W, 160);
    let f = scroll * 0.2;
    for (let x = -(f % 60); x < W; x += 60) {
      ctx.fillStyle = '#222'; ctx.fillRect(x, 0, 40, 260);
      ctx.fillStyle = '#333'; ctx.fillRect(x+2, 2, 36, 256);
    }
    ctx.fillStyle = '#111'; ctx.fillRect(0, GROUND, W, H - GROUND);
    ctx.fillStyle = '#554422'; ctx.fillRect(0, GROUND-2, W, 2);
    let m = scroll * 0.6;
    for (let x = -(m % 160); x < W; x += 160) {
      ctx.fillStyle = '#444'; ctx.fillRect(x+40, GROUND-25, 80, 20);
      ctx.fillStyle = '#222'; ctx.fillRect(x+40, GROUND-30, 80, 5);
      ctx.fillStyle = '#88aaff'; ctx.fillRect(x+45, GROUND-18, 10, 5);
      ctx.fillStyle = '#ff5555'; ctx.fillRect(x+105, GROUND-18, 10, 5);
    }
    if(Math.sin(t*4) > 0.5) { ctx.fillStyle = '#ffcc55'; for(let i=0;i<4;i++) ctx.fillRect(i*120+20, 110, 20, 3); }
  } },
  { name: 'COPY ROOM', draw(ctx, W, H, GROUND, scroll, t) {
    ctx.fillStyle = '#152025'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#223035'; ctx.fillRect(0, 0, W, 100);
    let f = scroll * 0.2;
    for (let x = -(f % 80); x < W; x += 80) {
      ctx.fillStyle = '#334455'; ctx.fillRect(x+5, 10, 70, 80);
      ctx.fillStyle = '#556677'; ctx.fillRect(x+5, 10, 70, 5);
    }
    ctx.fillStyle = '#1a1a25'; ctx.fillRect(0, 100, W, 160);
    ctx.fillStyle = '#101015'; ctx.fillRect(0, GROUND, W, H - GROUND);
    let m = scroll * 0.6;
    for (let x = -(m % 100); x < W; x += 100) {
      ctx.fillStyle = '#444'; ctx.fillRect(x+10, GROUND-40, 60, 40);
      ctx.fillStyle = '#222'; ctx.fillRect(x+15, GROUND-35, 50, 25);
      ctx.fillStyle = '#556677'; ctx.fillRect(x+20, GROUND-32, 40, 15);
      if(Math.sin(t*2+x)>0) { ctx.fillStyle = '#33ff66'; ctx.fillRect(x+50, GROUND-32, 4, 4); } else { ctx.fillStyle = '#ff3333'; ctx.fillRect(x+50, GROUND-32, 4, 4); }
      ctx.fillStyle = '#dddde5'; ctx.fillRect(x+20, GROUND-10, 30, 3);
    }
  } }
];
window.SCENES = SCENES;
