// An open page follows what happens without a new tab: a correction reloads it in place, a run that starts or ends
// shows that session. Builds the made-up tidepool project in a temporary folder and drives a headless Chromium.
// usage: node dev/check_live.mjs <chromium>     (Node 22 or later; dev/check_page.py finds a browser)
import {spawn, execFileSync} from 'node:child_process';
import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path';
const R = path.resolve(import.meta.dirname, '..'), bin = process.argv[2];
const S1 = '953c0ab1-134d-56c9-9224-a2eb69918a2a', S2 = '0a182a7b-3fd8-56b9-a6e6-9fc77576e221';
const T = fs.mkdtempSync(path.join(os.tmpdir(), 'treesight-live-'));
const env = {...process.env, TREESIGHT_HOME: T + '/home', TREESIGHT_WORK: T + '/work', TREESIGHT_PROJECTS: R + '/fixtures/projects'};
const ts = (...a) => JSON.parse(execFileSync('python3', [R + '/scripts/treesight.py', ...a, '--current', S1, '--cache', T + '/cache'], {env}).toString());
const sleep = ms => new Promise(r => setTimeout(r, ms));
let p = ts('prepare'); fs.copyFileSync(R + '/fixtures/extract/tidepool-1.json', p.extract); ts('apply'); const page = ts('build', '--done', '--session', S1).url;
const port = 9400 + Math.floor(Math.random() * 400), args = [`--remote-debugging-port=${port}`, `--user-data-dir=${T}/profile`,
  '--use-mock-keychain', '--password-store=basic', '--no-first-run', 'about:blank'];
if (path.basename(bin) !== 'chrome-headless-shell') args.unshift('--headless=new', ...(process.platform === 'linux' ? ['--no-sandbox'] : []));
const proc = spawn(bin, args, {stdio: 'ignore'});
const fail = [];
try {
  let list; for (let i = 0; i < 100 && !list; i++) { try { list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json() } catch { await sleep(100) } }
  const ws = new WebSocket(list.find(t => t.type === 'page').webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
  let seq = 0; const pend = new Map(); ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id) } };
  const send = (method, params = {}) => new Promise(res => { const id = ++seq; pend.set(id, res); ws.send(JSON.stringify({id, method, params})) });
  // a page in the middle of reloading has no answer yet: {} and the caller tries again
  const state = async () => { try { return JSON.parse((await send('Runtime.evaluate', {returnByValue: true, expression:
    `JSON.stringify((d=>({v:d.version,hash:location.hash,pending:!!d.pending,focus:(d.focus||'').slice(0,8)}))(JSON.parse(document.getElementById('data').textContent)))`})).result.value) } catch { return {} } };
  // waits up to 12 s for the page to show what was just built (a page that is not drawing checks every 5 s)
  const until = async (want, why) => { let s; for (let i = 0; i < 60; i++) { s = await state(); if (Object.entries(want).every(([k, v]) => s[k] === v)) return; await sleep(200) } fail.push(why + ': ' + JSON.stringify(s)) };
  await send('Page.navigate', {url: page + '#p'}); await sleep(1000);
  const first = (await state()).v;
  ts('edit', 'hide', 'Windows', 'support'); ts('build');
  await until({hash: '#p', focus: ''}, 'a correction reloads the page in place');
  if ((await state()).v === first) fail.push('the page kept its old build after a correction');
  p = ts('prepare', '--session', S2); ts('build', '--session', S2);
  await until({hash: '', pending: true, focus: '0a182a7b'}, 'a run that starts shows its session');
  fs.copyFileSync(R + '/fixtures/extract/tidepool-2.json', p.extract); ts('apply', '--session', S2); ts('build', '--done', '--session', S2);
  await until({pending: false, focus: '0a182a7b'}, 'a run that ends shows its result');
  // a page with no view in its address (as the browser first opens it) keeps showing the same session after a correction
  ts('edit', 'hide', 'lightning', 'talk', 'proposal'); ts('build');
  await until({hash: '#s=0a182a7b', focus: ''}, 'a correction keeps the session the page showed');
} finally {
  // the browser writes to its profile while it shuts down (on Linux, removing the folder at once failed with ENOTEMPTY)
  const gone = new Promise(r => { proc.once('exit', r); setTimeout(r, 5000) }); proc.kill(); if (proc.exitCode === null) await gone;
  fs.rmSync(T, {recursive: true, force: true, maxRetries: 10, retryDelay: 200})
}
console.log(fail.length ? fail.join('\n') : 'ok: the open page followed corrections, a run starting and a run ending');
process.exit(fail.length ? 1 : 0);
