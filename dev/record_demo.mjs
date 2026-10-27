#!/usr/bin/env node
// Record the README tour video from the made-up recipe-box sample, as a project's first run: a cover with the three
// chapters; the command typed in a Claude Code session; the page within seconds, still drawing; "about 4 minutes
// later"; the session's tree growing; a click on the node that got stuck and on one of its quotes; the project's open
// items; the report back in the conversation; an end card with the install command. The pages and the report come
// from dev/make_sample.py --first-run, so they are what the plugin's own code builds. The terminal is drawn from a real
// run's screen (its prompt, "Running in the background", the finished notice), with the sample session's own last turns
// above it. The pages' animations and transitions are paused and stepped on a virtual clock through the Chrome DevTools
// Protocol, and a camera zooms to where the action is: each frame is a clip of the page rendered at the zoom, so text
// stays sharp, stacked over the caption band. Two runs gave the same video frame for frame (2026-10-27). Needs Node 22
// or later, ffmpeg, and Chromium's headless shell
// (`npx playwright install chromium-headless-shell`, or set CH to a Chromium binary).
// Usage: node dev/record_demo.mjs en|zh [out.mp4]
import {spawn, spawnSync} from 'node:child_process';
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import {fileURLToPath} from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// chapters are the cover's and the band's numbers; each caption belongs to one (CH)
const LANGS = {
  en: {sample: 'recipe-box', src: 'recipe-1.json', session: '0c4f931d', node: 'Phone photos upload fine', locale: 'en-US', out: 'treesight-tour.mp4',
    chapters: ['Session tree', 'Open a node', 'Everything still open'],
    captions: ['Run /treesight:treesight in a session',
      'The page opens within seconds; the run takes a few minutes',
      'Then the session becomes a tree: what got done, what was found, where it got stuck',
      'Open a node: how long it was stuck, how it was solved, each with its quote',
      'Everything still open in the project, in one list',
      'Then a short report in your conversation: what changed, and the link'],
    later: 'About 4 minutes later', install: 'Install in Claude Code:', then: 'Then run it in the session you want to see:'},
  zh: {sample: 'recipe-box-zh', src: 'recipe-zh-1.json', session: '706417bf', node: '手机照片能上传了', locale: 'zh-CN', out: 'treesight-tour-zh.mp4',
    chapters: ['会话树', '点开一个节点', '所有还没做完的事'],
    captions: ['在会话里运行 /treesight:treesight',
      '几秒内打开本地页面，后台花几分钟读完整个会话',
      '读完后，会话画成一棵树：做完了什么、查清了什么、卡在哪',
      '点开一个节点：卡了多久、怎么解决的，每条都有原话',
      '整个项目还没做完的事，一张清单',
      '跑完后，对话里只有简短的报告：变了什么，附上页面链接'],
    later: '约 4 分钟后', install: '在 Claude Code 里安装：', then: '然后在想看的会话里运行：'},
};
const CH = [1, 1, 1, 2, 3, 3];
const W = 1100, H = 688, CAPH = 46, PH = H - CAPH, DPR = 2, FPS = 30, DT = 1000 / FPS, SCROLL = 170;   // wider than the page's 1020 px breakpoint
const START = '2026-10-03T09:00:20Z';   // the pages' clock: the samples' run time (dev/make_sample.py) plus 20 s
const COVER = 1.7, END = 3, FADE = 0.5;   // seconds

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
const run = (cmd, args) => { const r = spawnSync(cmd, args, {cwd: ROOT, encoding: 'utf8'});
  if (r.error || r.status !== 0) throw new Error(cmd + ' failed: ' + (r.error ? r.error.message : r.stderr)); return r };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

// the first run's pages and report, built the way the plugin builds them
run('python3', ['dev/make_sample.py', '--sample', L.sample, '--first-run', tmp]);
const report = fs.readFileSync(path.join(tmp, 'report.txt'), 'utf8').trim().split('\n');
const turns = JSON.parse(fs.readFileSync(path.join(ROOT, 'fixtures/src', L.src), 'utf8')).events.filter(e => e.k === 'prompt' || e.k === 'reply').slice(-10);

// the cover and the end card
const logo = fs.readFileSync(path.join(ROOT, 'docs/logo.svg'), 'utf8').replace(/<style>[\s\S]*?<\/style>\n?/, '');
const card = (inner, size) => `<!doctype html><html lang="${L.locale}"><meta charset="utf-8"><style>
body{margin:0;width:${W}px;height:${H}px;background:#0f1013;color:#E9E8E3;font:500 16px/1.4 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px}
h1{font-size:48px;margin:14px 0 0;letter-spacing:-.5px}ol{list-style:none;padding:0;margin:34px 0 0;display:flex;gap:14px}
li{background:#181a1e;border:1px solid #2a2c31;border-radius:12px;padding:12px 18px;font-size:16px;display:flex;gap:10px;align-items:center}
li b{font:600 12px/1 ui-monospace,Menlo,monospace;color:#131417;background:#C8FF00;border-radius:999px;padding:5px 8px}
code{font:500 21px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;background:#181a1e;border:1px solid #2a2c31;border-radius:10px;padding:12px 18px}
small{color:#8b8f97;font-size:16px;margin-top:4px}
</style><body>${logo.replace(/width="\d+" height="\d+"/, `width="${size}" height="${size}"`)}${inner}</body></html>`;
fs.writeFileSync(path.join(tmp, 'cover.html'), card(`<h1>treesight</h1><ol>${L.chapters.map((s, i) => `<li><b>${i + 1}</b>${esc(s)}</li>`).join('')}</ol>`, 104));
fs.writeFileSync(path.join(tmp, 'end.html'), card(`<h1 style="font-size:36px">treesight</h1><small>${esc(L.install)}</small><code>/plugin install treesight --marketplace kuk1song/treesight</code><small style="margin-top:14px">${esc(L.then)}</small><code>/treesight:treesight</code>`, 64));
// the terminal
fs.writeFileSync(path.join(tmp, 'term.html'), `<!doctype html><html lang="${L.locale}"><meta charset="utf-8"><style>
body{margin:0;width:${W}px;height:${H}px;background:#0f1013;font:17px/1.6 ui-monospace,SFMono-Regular,Menlo,"PingFang SC",monospace;color:#d7dae0}
.win{position:absolute;inset:22px 30px ${CAPH + 22}px;background:#16181c;border:1px solid #2a2c31;border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.bar{height:34px;display:flex;align-items:center;gap:8px;padding:0 14px;border-bottom:1px solid #2a2c31;color:#8b8f97;font-size:13px}
.bar i{width:11px;height:11px;border-radius:50%;background:#3a3d44}.bar span{margin-left:10px}
.out{flex:1;padding:16px 22px 0;display:flex;flex-direction:column;justify-content:flex-end;gap:6px;overflow:hidden}
.l{white-space:pre-wrap;word-break:break-all}.dim{color:#7d828b}.g{color:#7ee787}.w{color:#e9e8e3}.hide{display:none}
.in{margin:12px 22px 18px;border-top:1px solid #3a3d44;border-bottom:1px solid #3a3d44;padding:9px 4px;color:#e9e8e3}
.in b{color:#8b8f97;font-weight:400;margin-right:10px}.caret{display:inline-block;width:9px;height:18px;background:#d7dae0;vertical-align:-3px;margin-left:1px}
</style><body><div class="win"><div class="bar"><i></i><i></i><i></i><span>claude · ~/recipe-box</span></div><div class="out">
${turns.map(e => `<div class="l dim">${e.k === 'prompt' ? '&gt;' : '⏺'} ${esc(e.text)}</div>`).join('\n')}
<div class="l w hide" id="a1">❯ /treesight:treesight</div>
<div class="l dim hide" id="a2">  ⎿  Running in the background</div>
<div class="l g hide" id="b1">⏺ Agent "/treesight:treesight" finished · 4m 02s</div>
<div class="l w hide" id="b2">⏺ ${esc(report[0])}</div>
<div class="l w hide" id="b3">  ${esc(report[1])}</div>
</div><div class="in"><b>❯</b><span id="typed"></span><span class="caret"></span></div></div>
<script>const CMD='/treesight:treesight';window.__type=n=>{document.getElementById('typed').textContent=CMD.slice(0,n)};
window.__show=(...ids)=>ids.forEach(i=>document.getElementById(i).classList.remove('hide'))</script></body></html>`);

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

// added to each page after it loads: the cursor, the click ring, the "later" chip, the caption band, the virtual clock
const OVERLAY = `(()=>{if(window.__ov)return;window.__ov=1;const st=document.createElement('style');st.textContent=\`
#cur{position:fixed;left:0;top:0;z-index:100000;pointer-events:none;width:22px;height:22px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.6));opacity:0}
#rip{position:fixed;z-index:99999;pointer-events:none;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:2px solid #C8FF00;opacity:0}
#later{position:fixed;left:50%;top:44%;z-index:99997;pointer-events:none;transform:translate(-50%,-50%);background:rgba(24,26,30,.96);border:1px solid #3a3d44;border-radius:999px;padding:12px 26px;font:600 22px/1 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",sans-serif;color:#E9E8E3;opacity:0;display:flex;gap:12px;align-items:center}
#later u{width:10px;height:10px;border-radius:50%;background:#C8FF00}
#cap{position:fixed;left:0;right:0;bottom:0;height:${CAPH}px;z-index:99998;pointer-events:none;display:flex;align-items:center;gap:12px;padding:0 18px;background:#101114;border-top:1px solid #2a2c31;font:500 15px/1.2 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",sans-serif;color:#E9E8E3}
#cap b{font:600 12px/1 ui-monospace,Menlo,monospace;color:#131417;background:#C8FF00;border-radius:999px;padding:5px 8px;flex:none}
#cap span{flex:1}#cap i{display:flex;gap:6px;flex:none}#cap i u{width:7px;height:7px;border-radius:50%;background:#3D4048}#cap i u.on{background:#C8FF00}
#bar{position:absolute;left:0;top:-1px;height:2px;background:#C8FF00;width:0}\`;document.head.append(st);
const c=document.createElement('div');c.id='cur';c.innerHTML='<svg viewBox="0 0 22 22" width="22" height="22"><path d="M4 2.5v15.2l4-3.9 2.7 6.2 2.9-1.3-2.7-6.1h5.6z" fill="#fff" stroke="#000" stroke-width="1.3" stroke-linejoin="round"/></svg>';
const r=document.createElement('div');r.id='rip';const k=document.createElement('div');k.id='later';k.innerHTML='<u></u>'+${JSON.stringify(esc(L.later))};
const cap=document.createElement('div');cap.id='cap';cap.innerHTML='<div id="bar"></div><b></b><span></span><i>'+'<u></u>'.repeat(${L.chapters.length})+'</i>';document.body.append(c,r,k,cap);
window.__vt=0;
window.__tick=dt=>{__vt+=dt;for(const a of document.getAnimations()){if(a.__t0===undefined){a.__t0=__vt-dt;a.pause()}a.currentTime=Math.max(0,__vt-a.__t0)*(a.playbackRate||1)}};
window.__cur=(x,y,o)=>{c.style.transform='translate('+(x-4)+'px,'+(y-2)+'px)';c.style.opacity=o};
window.__rip=(x,y,q)=>{r.style.left=x+'px';r.style.top=y+'px';r.style.opacity=q<0?0:(1-q)*.9;r.style.transform='scale('+(.4+q*.9)+')'};
window.__later=o=>{k.style.opacity=o};
window.__cap=(n,txt,p)=>{cap.style.visibility='visible';cap.querySelector('b').textContent=n+'/'+${L.chapters.length};cap.querySelector('span').textContent=txt;
  cap.querySelectorAll('u').forEach((u,i)=>u.classList.toggle('on',i<n));document.getElementById('bar').style.width=(p*100)+'%'};
for(const a of document.getAnimations()){a.__t0=0;a.pause();a.currentTime=0}})()`;

const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
let frame = 0, total = 1, cx, cy, cop, step, cam, tw, dry, sy = 0;   // sy: the page's scroll, as clips are in page px
const rect = sel => dry ? {x: 0, y: 0, w: 10, h: 10} : js(`(()=>{const e=${sel};if(!e)throw new Error('not found: '+${JSON.stringify(sel)});const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()`);
// the camera: the part of the viewport shown (x, y, zoom), eased between targets while the plan goes on
const WHOLE = {x: 0, y: 0, z: 1};
const camAt = () => { if (!tw) return cam; const q = Math.min(1, (frame - tw.k0) / tw.n), e = ease(q);
  const c = {x: tw.a.x + (tw.b.x - tw.a.x) * e, y: tw.a.y + (tw.b.y - tw.a.y) * e, z: tw.a.z + (tw.b.z - tw.a.z) * e}; if (q >= 1) { cam = tw.b; tw = null } return c };
const camTo = (b, ms) => { tw = {a: camAt(), b, k0: frame, n: Math.max(1, Math.round(ms / DT))} };
const aim = (r, z) => { const w = W / z, h = PH / z, x = r.x + r.w / 2 - w / 2, y = r.y + r.h / 2 - h / 2;
  return {x: Math.max(0, Math.min(W - w, x)), y: Math.max(0, Math.min(PH - h, y)), z} };
const f = async (speed = 1) => {
  const c = camAt();
  if (!dry) {
    await js(`__tick(${DT * speed});__cur(${cx},${cy},${cop});__cap(${CH[step - 1]},${JSON.stringify(L.captions[step - 1])},${frame / total})`);
    const band = await send('Page.captureScreenshot', {format: 'png', clip: {x: 0, y: PH + sy, width: W, height: CAPH, scale: 1}});
    await js(`document.getElementById('cap').style.visibility='hidden'`);
    const pg = await send('Page.captureScreenshot', {format: 'png', clip: {x: c.x, y: c.y + sy, width: W / c.z, height: PH / c.z, scale: c.z}});
    const n = String(frame).padStart(4, '0');
    fs.writeFileSync(path.join(frames, 'p' + n + '.png'), Buffer.from(pg.data, 'base64'));
    fs.writeFileSync(path.join(frames, 'b' + n + '.png'), Buffer.from(band.data, 'base64'));
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
const scroll = async (dy, ms) => { const k = Math.round(ms / DT), y0 = sy;
  for (let i = 1; i <= k; i++) { sy = y0 + dy * ease(i / k); if (!dry) await js(`scrollTo(0,${sy})`); await f() } };
const fade = async (to, ms) => { const k = Math.round(ms / DT), o0 = cop; for (let i = 1; i <= k; i++) { cop = o0 + (to - o0) * i / k; await f() } };
const open = async (file, hash = '', after = '') => { sy = 0; if (dry) return; await load('file://' + path.join(tmp, file) + hash); await js(OVERLAY); if (after) await js(after) };

async function play() {
  frame = 0; cx = W * .86; cy = H * .22; cop = 0; step = 1; cam = WHOLE; tw = null;   // the cursor starts over empty space
  // 1: the command, typed in the session
  await open('term.html');
  await hold(300); for (let n = 1; n <= 20; n++) { if (!dry) await js(`__type(${n})`); await hold(DT) }
  await hold(350); if (!dry) await js(`__type(0);__show('a1')`); await hold(400); if (!dry) await js(`__show('a2')`); await hold(1600);
  // 2: the page within seconds, still drawing; then about four minutes later
  step = 2; await open('pending.html', '#t=0'); cam = aim({x: 150, y: 0, w: 800, h: 300}, 1.3);
  await hold(2600); for (let i = 1; i <= 8; i++) { if (!dry) await js(`__later(${i / 8})`); await f() } await hold(700);
  // 3: the session's tree grows: its first 0.3 s at normal speed, the rest slowed
  step = 3; await open('done.html', '#s=' + L.session + '&t=0'); cam = aim({x: 250, y: 0, w: 600, h: 560}, 1.12);
  await hold(300); await hold(3600, 1000 / 3600); await hold(1300);
  // 4: the node that got stuck, then the quote behind one of its twigs
  step = 4; let r = await rect(`[...document.querySelectorAll('.node')].find(b=>b.textContent.includes(${JSON.stringify(L.node)}))`);
  await fade(1, 200); await move(r.x + r.w * .6, r.y + 12, 800); await hold(150); await click();
  camTo(aim({x: r.x - 330, y: r.y - 10, w: 560, h: 400}, 1.5), 700); await hold(1500);
  await scroll(SCROLL, 600); camTo(aim({x: r.x - 330, y: r.y - SCROLL + 60, w: 560, h: 400}, 1.5), 600);
  r = await rect(`document.querySelector('.slot.open .twl .qm')`);
  await move(r.x + r.w / 2, r.y + r.h / 2, 700); await hold(150); await click();
  r = await rect(`document.querySelector('.slot.open .qs:not([hidden])')`); camTo(aim({x: r.x - 60, y: r.y - 150, w: r.w + 120, h: r.h + 190}, 1.5), 500); await hold(2300);
  // 5: the whole project and its open items, the list framed from its title down
  step = 5; camTo(WHOLE, 700); await scroll(-SCROLL, 500); r = await rect(`document.getElementById('back')`);
  await move(r.x + r.w / 2, r.y + r.h / 2, 750); await hold(150); await click(); await hold(1300, .6);
  r = await rect(`document.querySelector('.todo')`);
  await move(r.x + r.w / 2, r.y + r.h / 2, 800); await hold(150); await click(); await move(r.x + r.w / 2 - 40, r.y + 160, 500);
  camTo(aim({x: W - 470, y: 0, w: 470, h: PH / 1.3}, 1.3), 800); await fade(0, 300); await hold(2400);
  // 6: the report, back in the conversation
  step = 6; await open('term.html', '', `__show('a1','a2')`); cam = WHOLE;
  await hold(300); if (!dry) await js(`__show('b1')`); await hold(600); if (!dry) await js(`__show('b2','b3')`); await hold(3000);
  return frame;
}

try {
  await send('Page.enable');
  await send('Emulation.setTimezoneOverride', {timezoneId: 'UTC'});    // the sample's times as written, on any machine
  await send('Emulation.setDeviceMetricsOverride', {width: W, height: H, deviceScaleFactor: DPR, mobile: false});
  // the pages' clock is the sample's, moving with the virtual clock, so a page still drawing does not look stopped
  await send('Page.addScriptToEvaluateOnNewDocument', {source: `(()=>{const R=Date,T0=R.parse('${START}');class D extends R{constructor(...a){if(a.length)super(...a);else super(T0+(window.__vt||0))}static now(){return T0+(window.__vt||0)}}D.parse=R.parse;D.UTC=R.UTC;window.Date=D})()`});
  for (const c of ['cover', 'end']) { await load('file://' + path.join(tmp, c + '.html')); fs.writeFileSync(path.join(tmp, c + '.png'), Buffer.from((await send('Page.captureScreenshot', {format: 'png'})).data, 'base64')) }
  dry = true; total = await play(); dry = false; await play();
} finally {
  ws.close(); proc.kill(); await new Promise(r => proc.on('exit', r)); fs.rmSync(prof, {recursive: true, force: true, maxRetries: 5});
}
// the cover, a fade into the recording (each frame the page over the band), a fade into the end card; H.264 so every browser plays it
const D = frame / FPS;
run('ffmpeg', ['-y', '-loglevel', 'error', '-loop', '1', '-framerate', String(FPS), '-t', String(COVER + FADE), '-i', path.join(tmp, 'cover.png'),
  '-framerate', String(FPS), '-i', path.join(frames, 'p%04d.png'), '-framerate', String(FPS), '-i', path.join(frames, 'b%04d.png'),
  '-loop', '1', '-framerate', String(FPS), '-t', String(END), '-i', path.join(tmp, 'end.png'), '-filter_complex',
  `[1][2]vstack,format=yuv420p,setsar=1[rec];[0]format=yuv420p,setsar=1[a];[3]format=yuv420p,setsar=1[e];` +
  `[a][rec]xfade=transition=fade:duration=${FADE}:offset=${COVER}[ar];[ar][e]xfade=transition=fade:duration=${FADE}:offset=${(COVER + D - FADE).toFixed(3)},scale=1600:-2:flags=lanczos,setsar=1`,
  '-c:v', 'libx264', '-preset', 'slow', '-crf', '21', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-tune', 'animation', OUT]);
if (!process.env.KEEP) fs.rmSync(tmp, {recursive: true, force: true});
console.log(JSON.stringify({video: OUT, seconds: +(COVER + D - FADE + END).toFixed(1), bytes: fs.statSync(OUT).size, ...(process.env.KEEP ? {frames} : {})}));
