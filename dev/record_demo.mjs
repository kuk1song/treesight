#!/usr/bin/env node
// Record the README tour video from the made-up recipe-box sample: a cover, the session's tree growing, a click on
// the node that got stuck and on its quotes, then back to the project and its open items. The page's own animations
// and transitions are paused and stepped on a virtual clock through the Chrome DevTools Protocol, so every frame is
// exact and each run gives the same video. A drawn cursor and a caption band are added to the page for the recording.
// Needs Node 22 or later, ffmpeg, and Chromium's headless shell (`npx playwright install chromium-headless-shell`,
// or set CH to a Chromium binary). Usage: node dev/record_demo.mjs en|zh [out.mp4]
import {spawn, spawnSync} from 'node:child_process';
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import {fileURLToPath} from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const LANGS = {
  en: {sample: 'recipe-box', session: '0c4f931d', node: 'Phone photos upload fine', locale: 'en-US', out: 'treesight-tour.mp4',
    cover: {steps: ["A session's tree", 'Open a node', 'Everything still open'], foot: 'A short tour of a made-up recipe app'},
    captions: ['Run /treesight:treesight in a session, and its tree grows on a local page',
      'Open a node: where it got stuck, for how long, and the quote behind it',
      'The project: everything still open, from every session, in one list']},
  zh: {sample: 'recipe-box-zh', session: '706417bf', node: '手机照片能上传了', locale: 'zh-CN', out: 'treesight-tour-zh.mp4',
    cover: {steps: ['会话的树', '点开一个节点', '所有还没做完的事'], foot: '用一个编造的菜谱网站演示一遍'},
    captions: ['在会话里运行 /treesight:treesight,它的树会在本地页面上长出来',
      '点开一个节点:卡在哪、卡了多久,以及原话',
      '整个项目:所有会话里还没做完的事,一张清单']},
};
const W = 1100, H = 688, DPR = 2, FPS = 30, DT = 1000 / FPS, SCROLL = 170;   // wider than the page's 1020 px breakpoint

const lang = process.argv[2], L = LANGS[lang];
if (!L) { console.error('usage: node dev/record_demo.mjs en|zh [out.mp4]'); process.exit(2) }
const OUT = path.resolve(process.argv[3] || L.out);

function chromium() {
  if (process.env.CH) return process.env.CH;
  for (const base of [path.join(os.homedir(), 'Library/Caches/ms-playwright'), path.join(os.homedir(), '.cache/ms-playwright')]) {
    if (!fs.existsSync(base)) continue;
    for (const d of fs.readdirSync(base).filter(d => d.startsWith('chromium_headless_shell-')).sort().reverse())
      for (const s of fs.readdirSync(path.join(base, d))) {
        const p = path.join(base, d, s, 'chrome-headless-shell');
        if (fs.existsSync(p)) return p;
      }
  }
  throw new Error('no chrome-headless-shell; run: npx playwright install chromium-headless-shell, or set CH');
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'treesight-demo-'));
const frames = path.join(tmp, 'frames'); fs.mkdirSync(frames);
const run = (cmd, args) => { const r = spawnSync(cmd, args, {cwd: ROOT, encoding: 'utf8'}); if (r.status) throw new Error(cmd + ' failed:\n' + r.stderr); return r };
const sleep = ms => new Promise(r => setTimeout(r, ms));

// the page, built from the fixtures the same way the plugin builds pages; it counts days to the sample's own date
run('python3', ['dev/make_sample.py', '--sample', L.sample, '--out', path.join(tmp, 'page.html')]);
// the cover: the logo at rest, the name, the three steps; the README shows the tagline right above the video
const logo = fs.readFileSync(path.join(ROOT, 'docs/logo.svg'), 'utf8').replace(/<style>[\s\S]*?<\/style>\n?/, '').replace('width="72" height="72"', 'width="104" height="104"');
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
fs.writeFileSync(path.join(tmp, 'cover.html'), `<!doctype html><html lang="${L.locale}"><meta charset="utf-8"><style>
body{margin:0;width:${W}px;height:${H}px;background:#0f1013;color:#E9E8E3;font:500 16px/1.4 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px}
h1{font-size:48px;margin:14px 0 0;letter-spacing:-.5px}ol{list-style:none;padding:0;margin:34px 0 0;display:flex;gap:14px}
li{background:#181a1e;border:1px solid #2a2c31;border-radius:12px;padding:12px 18px;font-size:16px;display:flex;gap:10px;align-items:center}
li b{font:600 12px/1 ui-monospace,Menlo,monospace;color:#131417;background:#C8FF00;border-radius:999px;padding:5px 8px}
.t{margin-top:30px;color:#8b8a86;font-size:15px}.t span{color:#C8FF00}</style>
<body>${logo}<h1>treesight</h1><ol>${L.cover.steps.map((s, i) => `<li><b>${i + 1}</b>${esc(s)}</li>`).join('')}</ol><div class="t"><span>&#9654;</span>&nbsp; ${esc(L.cover.foot)}</div></body></html>`);

const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'treesight-chrome-'));
const port = 9300 + Math.floor(Math.random() * 500);
const proc = spawn(chromium(), ['--hide-scrollbars', `--remote-debugging-port=${port}`, `--user-data-dir=${prof}`, `--lang=${L.locale}`, `--window-size=${W},${H}`, 'about:blank'], {stdio: 'ignore'});
let list;
for (let i = 0; i < 100 && !list; i++) { try { list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json() } catch { await sleep(100) } }
const ws = new WebSocket(list.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let seq = 0; const pend = new Map(), events = [];
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { const p = pend.get(m.id); pend.delete(m.id); m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result) } else events.push(m) };
const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pend.set(id, {res, rej}); ws.send(JSON.stringify({id, method, params})) });
const js = async expr => { const r = await send('Runtime.evaluate', {expression: expr, returnByValue: true, awaitPromise: true}); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails)); return r.result.value };
const load = async url => { events.length = 0; await send('Page.navigate', {url}); for (let i = 0; i < 100 && !events.some(m => m.method === 'Page.loadEventFired'); i++) await sleep(50); await sleep(300) };

try {
  await send('Page.enable');
  await send('Emulation.setTimezoneOverride', {timezoneId: 'UTC'});    // the sample's times as written, on any machine
  await send('Emulation.setDeviceMetricsOverride', {width: W, height: H, deviceScaleFactor: DPR, mobile: false});
  await load('file://' + path.join(tmp, 'cover.html'));
  fs.writeFileSync(path.join(tmp, 'cover.png'), Buffer.from((await send('Page.captureScreenshot', {format: 'png'})).data, 'base64'));
  await load('file://' + path.join(tmp, 'page.html') + '#s=' + L.session + '&t=0');   // growth paused at its start

  // the cursor, the click ring, the caption band, and the virtual clock that steps every animation on the page
  await js(`(()=>{const st=document.createElement('style');st.textContent=\`
    #cur{position:fixed;left:0;top:0;z-index:100000;pointer-events:none;width:22px;height:22px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.6));opacity:0}
    #rip{position:fixed;z-index:99999;pointer-events:none;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:2px solid #C8FF00;opacity:0}
    #cap{position:fixed;left:0;right:0;bottom:0;height:46px;z-index:99998;display:flex;align-items:center;gap:12px;padding:0 18px;background:rgba(16,17,20,.94);border-top:1px solid #2a2c31;font:500 14.5px/1.2 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",sans-serif;color:#E9E8E3}
    #cap b{font:600 12px/1 ui-monospace,Menlo,monospace;color:#131417;background:#C8FF00;border-radius:999px;padding:5px 8px;flex:none}
    #cap span{flex:1}#cap i{display:flex;gap:6px;flex:none}#cap i u{width:7px;height:7px;border-radius:50%;background:#3D4048}#cap i u.on{background:#C8FF00}
    #bar{position:absolute;left:0;top:-1px;height:2px;background:#C8FF00;width:0}\`;document.head.append(st);
    const c=document.createElement('div');c.id='cur';c.innerHTML='<svg viewBox="0 0 22 22" width="22" height="22"><path d="M4 2.5v15.2l4-3.9 2.7 6.2 2.9-1.3-2.7-6.1h5.6z" fill="#fff" stroke="#000" stroke-width="1.3" stroke-linejoin="round"/></svg>';
    const r=document.createElement('div');r.id='rip';const cap=document.createElement('div');cap.id='cap';
    cap.innerHTML='<div id="bar"></div><b></b><span></span><i>'+'<u></u>'.repeat(${L.captions.length})+'</i>';document.body.append(c,r,cap);
    window.__vt=0;
    window.__tick=dt=>{__vt+=dt;for(const a of document.getAnimations()){if(a.__t0===undefined){a.__t0=__vt-dt;a.pause()}a.currentTime=Math.max(0,__vt-a.__t0)*(a.playbackRate||1)}};
    window.__cur=(x,y,o)=>{c.style.transform='translate('+(x-4)+'px,'+(y-2)+'px)';c.style.opacity=o};
    window.__rip=(x,y,k)=>{r.style.left=x+'px';r.style.top=y+'px';r.style.opacity=k<0?0:(1-k)*.9;r.style.transform='scale('+(.4+k*.9)+')'};
    window.__cap=(n,txt,p)=>{cap.querySelector('b').textContent=n+'/'+${L.captions.length};cap.querySelector('span').textContent=txt;
      cap.querySelectorAll('u').forEach((u,i)=>u.classList.toggle('on',i<n));document.getElementById('bar').style.width=(p*100)+'%'};
    for(const a of document.getAnimations()){a.__t0=0;a.pause();a.currentTime=0}})()`);

  const rect = sel => js(`(()=>{const e=${sel};if(!e)throw new Error('not found: '+${JSON.stringify(sel)});const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()`);
  const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  let frame = 0, total = 1, cx, cy, cop, step;
  // the plan runs twice: once without the browser to count frames (for the progress bar), once to record
  async function play(dry) {
    frame = 0; cx = W * .82; cy = H * .78; cop = 0; step = 1;
    const at = sel => dry ? {x: 0, y: 0, w: 0, h: 0} : rect(sel);
    const f = async (speed = 1) => {
      if (!dry) {
        await js(`__tick(${DT * speed});__cur(${cx},${cy},${cop});__cap(${step},${JSON.stringify(L.captions[step - 1])},${frame / total})`);
        fs.writeFileSync(path.join(frames, String(frame).padStart(4, '0') + '.png'), Buffer.from((await send('Page.captureScreenshot', {format: 'png'})).data, 'base64'));
      }
      frame++;
    };
    const hold = async (ms, speed = 1) => { for (let i = 0; i < Math.round(ms / DT); i++) await f(speed) };
    const move = async (tx, ty, ms) => { const x0 = cx, y0 = cy, k = Math.round(ms / DT);
      for (let i = 1; i <= k; i++) { const e = ease(i / k); cx = x0 + (tx - x0) * e; cy = y0 + (ty - y0) * e; if (!dry) await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: cx, y: cy}); await f() } };
    const click = async () => {
      if (!dry) for (const type of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', {type, x: cx, y: cy, button: 'left', clickCount: 1});
      const k = Math.round(420 / DT); for (let i = 0; i <= k; i++) { if (!dry) await js(`__rip(${cx},${cy},${i / k})`); await f() }
      if (!dry) await js('__rip(0,0,-1)');
    };
    const scroll = async (dy, ms) => { const k = Math.round(ms / DT), y0 = dry ? 0 : await js('scrollY');
      for (let i = 1; i <= k; i++) { if (!dry) await js(`scrollTo(0,${y0 + dy * ease(i / k)})`); await f() } };
    const fade = async (to, ms) => { const k = Math.round(ms / DT), o0 = cop; for (let i = 1; i <= k; i++) { cop = o0 + (to - o0) * i / k; await f() } };
    // 1: the tree grows, slowed to about 2.4 s
    await hold(300); await hold(2400, 1000 / 2400); await hold(900);
    // 2: open the node that got stuck, then its quotes
    step = 2; let r = await at(`[...document.querySelectorAll('.node')].find(b=>b.textContent.includes(${JSON.stringify(L.node)}))`);
    await fade(1, 200); await move(r.x + r.w * .6, r.y + 12, 800); await hold(200); await click(); await hold(1900);
    await scroll(SCROLL, 600); r = await at(`document.querySelector('.slot.open .acts button')`);
    await move(r.x + r.w / 2, r.y + r.h / 2, 700); await hold(150); await click(); await hold(2300);
    // 3: back to the whole project, then its open items
    step = 3; await scroll(-SCROLL, 500); r = await at(`document.getElementById('back')`);
    await move(r.x + r.w / 2, r.y + r.h / 2, 750); await hold(150); await click(); await hold(1300, .6);
    r = await at(`document.querySelector('.todo')`);
    await move(r.x + r.w / 2, r.y + r.h / 2, 800); await hold(150); await click(); await move(r.x + r.w / 2 - 40, r.y + 160, 500); await fade(0, 300); await hold(3000);
    return frame;
  }
  total = await play(true);
  await play(false);
} finally {
  ws.close(); proc.kill(); await new Promise(r => proc.on('exit', r)); fs.rmSync(prof, {recursive: true, force: true, maxRetries: 5});
}
// the cover for 1.7 s, a 0.5 s fade into the page, then the recording; H.264 so every browser plays it
run('ffmpeg', ['-y', '-loglevel', 'error', '-loop', '1', '-framerate', String(FPS), '-t', '2.2', '-i', path.join(tmp, 'cover.png'),
  '-framerate', String(FPS), '-i', path.join(frames, '%04d.png'), '-filter_complex',
  '[0]format=yuv420p,setsar=1[a];[1]format=yuv420p,setsar=1[b];[a][b]xfade=transition=fade:duration=0.5:offset=1.7,scale=1600:-2:flags=lanczos,setsar=1',
  '-c:v', 'libx264', '-preset', 'slow', '-crf', '21', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-tune', 'animation', OUT]);
if (!process.env.KEEP) fs.rmSync(tmp, {recursive: true, force: true});
console.log(JSON.stringify({video: OUT, bytes: fs.statSync(OUT).size, ...(process.env.KEEP ? {frames} : {})}));
