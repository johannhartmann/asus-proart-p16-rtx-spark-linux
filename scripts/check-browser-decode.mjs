#!/usr/bin/env node
// Check actual Chromium H.264 playback and the decoder reported by CDP Media.
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const output = process.argv[2];
if (!output) {
  console.error('Usage: node scripts/check-browser-decode.mjs RESULT.json [--nvidia-vaapi]');
  process.exit(2);
}
const nvidiaVaapi = process.argv.includes('--nvidia-vaapi');
const decodeFlags = nvidiaVaapi ? [
  '--enable-features=AcceleratedVideoDecodeLinuxGL,VaapiOnNvidiaGPUs,VaapiVideoDecoder',
  '--ignore-gpu-blocklist', '--use-gl=angle', '--use-angle=gl',
] : ['--enable-features=VaapiVideoDecoder'];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const temp = await mkdtemp(join(tmpdir(), 'n1x-browser-decode-'));
const video = join(temp, 'h264.mp4');
const fixture = spawnSync('ffmpeg', [
  '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
  '-i', 'testsrc2=size=320x180:rate=24', '-t', '4',
  '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
  '-y', video,
], {encoding:'utf8', timeout:20000});
if (fixture.status !== 0) {
  throw Error(`H.264 fixture failed: ${fixture.stderr}`);
}

const html = `<!doctype html><video id="player" muted autoplay playsinline src="/h264.mp4"></video><script>
window.playResult = new Promise((resolve, reject) => {
  const video = document.getElementById('player');
  const timeout = setTimeout(() => reject(Error('playback timeout')), 15000);
  video.onerror = () => { clearTimeout(timeout); reject(Error('video element error: ' + video.error?.message)); };
  video.onended = () => {
    clearTimeout(timeout);
    const quality = video.getVideoPlaybackQuality();
    resolve({width:video.videoWidth,height:video.videoHeight,
      totalVideoFrames:quality.totalVideoFrames,droppedVideoFrames:quality.droppedVideoFrames,
      duration:video.duration});
  };
  video.play().catch(reject);
});
</script>`;
const server = createServer(async (request, response) => {
  if (request.url === '/h264.mp4') {
    const body = await readFile(video);
    response.writeHead(200, {'content-type':'video/mp4','content-length':body.length,
      'accept-ranges':'none'});
    response.end(body);
  } else {
    response.writeHead(200, {'content-type':'text/html; charset=utf-8'});
    response.end(html);
  }
});
let chromium;
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  chromium = spawn('chromium', [
    `--user-data-dir=${temp}`, '--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0', '--no-first-run', '--disable-extensions',
    '--autoplay-policy=no-user-gesture-required',
    ...decodeFlags, '--ozone-platform=wayland',
    '--window-size=640,360', 'about:blank',
  ], {stdio:'ignore',
    env:{...process.env, LIBVA_DRIVER_NAME:'nvidia', NVD_BACKEND:'direct'}});
  let port;
  for (let i = 0; i < 100; i++) {
    try {
      port = Number((await readFile(join(temp, 'DevToolsActivePort'), 'utf8')).split('\n')[0]);
      break;
    } catch { await delay(100); }
  }
  if (!port) throw Error('Chromium DevTools port did not open');
  const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const ws = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  const pending = new Map();
  const media = [];
  let id = 0;
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.method?.startsWith('Media.')) media.push(message);
    if (pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  };
  const request = (method, params = {}) => new Promise(resolve => {
    const number = ++id;
    pending.set(number, resolve);
    ws.send(JSON.stringify({id:number,method,params}));
  });
  try {
    await request('Media.enable');
    await request('Page.navigate', {url:`http://127.0.0.1:${server.address().port}/`});
    await delay(500);
    const reply = await Promise.race([
      request('Runtime.evaluate', {expression:'window.playResult',awaitPromise:true,returnByValue:true}),
      delay(18000).then(() => { throw Error('Chromium playback timed out'); }),
    ]);
    const playback = reply.result?.result?.value;
    if (reply.error || reply.result?.exceptionDetails || !playback) {
      throw Error(JSON.stringify(reply.error || reply.result?.exceptionDetails || reply));
    }
    await delay(300);
    const properties = media.flatMap(event =>
      event.method === 'Media.playerPropertiesChanged' ? event.params.properties : []);
    const decoder = properties.filter(property =>
      /decoder|hardware|gpu|rendering/i.test(property.name));
    const vaapi = decoder.some(property => /VaapiVideoDecoder/i.test(property.value));
    const report = {status:vaapi ? 'pass' : 'unqualified',
      browser:'chromium', mode:nvidiaVaapi ? 'nvidia-vaapi-flags' : 'default-vaapi-flag',
      flags:decodeFlags, fixture:'generated H.264 320x180 24 fps',
      playback, decoder_properties:decoder,
      note:vaapi ? 'CDP Media explicitly identified VaapiVideoDecoder' :
        'Playback succeeded, but CDP Media did not establish VA-API hardware decoding'};
    await writeFile(output, JSON.stringify(report, null, 2) + '\n');
    console.log(`${report.status}: ${playback.totalVideoFrames} frames; ${decoder.length} decoder properties`);
    if (!vaapi) process.exitCode = 1;
  } finally { ws.close(); }
} finally {
  chromium?.kill('SIGTERM');
  server.close();
  await delay(300);
  if (chromium?.exitCode === null) chromium.kill('SIGKILL');
  await rm(temp, {recursive:true,force:true});
}
