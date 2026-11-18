#!/usr/bin/env node
// Check actual Chromium-family playback and the decoder reported by CDP Media.
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const output = process.argv[2];
if (!output) {
  console.error('Usage: node scripts/check-browser-decode.mjs RESULT.json [--nvidia-vaapi|--nvidia-vaapi-advanced|--no-test-flags] [--browser=COMMAND] [--size=WIDTHxHEIGHT] [--codec=h264|vp9|av1] [--seconds=1..60]');
  process.exit(2);
}
const nvidiaVaapi = process.argv.includes('--nvidia-vaapi');
const advancedVaapi = process.argv.includes('--nvidia-vaapi-advanced');
const browser = process.argv.find(arg => arg.startsWith('--browser='))?.split('=', 2)[1] ?? 'chromium';
const size = process.argv.find(arg => arg.startsWith('--size='))?.slice(7) ?? '320x180';
if (!/^[1-9]\d{1,3}x[1-9]\d{1,3}$/.test(size)) throw Error(`Invalid size ${size}`);
const codec = process.argv.find(arg => arg.startsWith('--codec='))?.slice(8) ?? 'h264';
if (!['h264', 'vp9', 'av1'].includes(codec)) throw Error(`Invalid codec ${codec}`);
const seconds = Number(process.argv.find(arg => arg.startsWith('--seconds='))?.slice(10) ?? '4');
if (!Number.isInteger(seconds) || seconds < 1 || seconds > 60) throw Error(`Invalid seconds ${seconds}`);
const browserVersion = spawnSync(browser, ['--version'], {encoding:'utf8', timeout:5000});
if (browserVersion.status !== 0) throw Error(`${browser} --version failed`);
const advancedFeatures = ['AcceleratedVideoDecodeLinuxGL',
  'AcceleratedVideoDecodeLinuxZeroCopyGL', 'VaapiOnNvidiaGPUs',
  'VaapiIgnoreDriverChecks', 'VaapiVideoDecoder'].filter(feature =>
  !(feature === 'AcceleratedVideoDecodeLinuxZeroCopyGL' && process.argv.includes('--no-zero-copy')) &&
  !(feature === 'VaapiIgnoreDriverChecks' && process.argv.includes('--no-ignore-checks')));
const decodeFlags = advancedVaapi ? [
  `--enable-features=${advancedFeatures.join(',')}`,
  '--ignore-gpu-blocklist',
  ...(!process.argv.includes('--no-disable-workarounds') ?
    ['--disable-gpu-driver-bug-workarounds'] : []),
  '--use-gl=angle', '--use-angle=gl',
] : nvidiaVaapi ? [
  '--enable-features=AcceleratedVideoDecodeLinuxGL,VaapiOnNvidiaGPUs,VaapiVideoDecoder',
  '--ignore-gpu-blocklist', '--use-gl=angle', '--use-angle=gl',
] : ['--enable-features=VaapiVideoDecoder'];
const launchFlags = process.argv.includes('--no-test-flags') ? [] : decodeFlags;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const temp = await mkdtemp(join(tmpdir(), 'n1x-browser-decode-'));
const extension = codec === 'vp9' ? 'webm' : 'mp4';
const video = join(temp, `fixture.${extension}`);
const fixtureCodecArgs = codec === 'h264' ?
  ['-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-movflags', '+faststart'] :
  codec === 'vp9' ?
    ['-c:v', 'libvpx-vp9', '-deadline', 'realtime', '-cpu-used', '8', '-b:v', '2M'] : [];
const fixtureInput = ['-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
  '-i', `testsrc2=size=${size}:rate=24`, '-t', String(seconds)];
try {
  if (codec === 'av1') {
    const y4m = join(temp, 'fixture.y4m');
    const ivf = join(temp, 'fixture.ivf');
    const raw = spawnSync('ffmpeg', [...fixtureInput, '-pix_fmt', 'yuv420p',
      '-f', 'yuv4mpegpipe', '-y', y4m],
    {encoding:'utf8', timeout:Math.max(60000, seconds * 3000)});
    if (raw.status !== 0) throw Error(`AV1 input fixture failed: ${raw.stderr}`);
    const encoded = spawnSync('aomenc', ['--rt', '--cpu-used=10', '--threads=8',
      '--ivf', '--passes=1', '--end-usage=q', '--cq-level=40', '-o', ivf, y4m],
    {encoding:'utf8', timeout:Math.max(60000, seconds * 8000)});
    if (encoded.status !== 0) throw Error(`AV1 encode failed: ${encoded.stderr}`);
    const mux = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error',
      '-i', ivf, '-c:v', 'copy', '-y', video],
    {encoding:'utf8', timeout:Math.max(20000, seconds * 1000)});
    if (mux.status !== 0) throw Error(`AV1 mux failed: ${mux.stderr}`);
  } else {
    const fixture = spawnSync('ffmpeg', [...fixtureInput, ...fixtureCodecArgs, '-y', video],
      {encoding:'utf8', timeout:Math.max(60000, seconds * 3000)});
    if (fixture.status !== 0) throw Error(`${codec} fixture failed: ${fixture.stderr}`);
  }
  const decoded = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-i', video,
    '-f', 'null', '-'], {encoding:'utf8', timeout:Math.max(30000, seconds * 3000)});
  if (decoded.status !== 0) throw Error(`Fixture fails independent decode: ${decoded.stderr}`);
} catch (error) {
  await rm(temp, {recursive:true,force:true});
  throw error;
}

const html = `<!doctype html><video id="player" muted autoplay playsinline src="/fixture.${extension}"></video><script>
window.playResult = new Promise((resolve, reject) => {
  const video = document.getElementById('player');
  const timeout = setTimeout(() => reject(Error('playback timeout')), (${seconds} + 12) * 1000);
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
  if (request.url === `/fixture.${extension}`) {
    const body = await readFile(video);
    response.writeHead(200, {'content-type':codec === 'vp9' ? 'video/webm' : 'video/mp4',
      'content-length':body.length,
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
  chromium = spawn(browser, [
    `--user-data-dir=${temp}`, '--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0', '--no-first-run', '--disable-extensions',
    '--autoplay-policy=no-user-gesture-required',
    ...launchFlags, '--ozone-platform=wayland',
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
    let timeoutHandle;
    let reply;
    try {
      reply = await Promise.race([
        request('Runtime.evaluate', {expression:'window.playResult',awaitPromise:true,returnByValue:true}),
        new Promise((_, reject) => {
          timeoutHandle = setTimeout(() => reject(Error('Chromium playback timed out')), (seconds + 15) * 1000);
        }),
      ]);
    } finally {
      clearTimeout(timeoutHandle);
    }
    const playback = reply.result?.result?.value;
    if (reply.error || reply.result?.exceptionDetails || !playback) {
      throw Error(JSON.stringify(reply.error || reply.result?.exceptionDetails || reply));
    }
    await delay(1000);
    const properties = media.flatMap(event =>
      event.method === 'Media.playerPropertiesChanged' ? event.params.properties : []);
    const decoder = properties.filter(property =>
      /decoder|hardware|gpu|rendering/i.test(property.name));
    const vaapi = decoder.some(property => /VaapiVideoDecoder/i.test(property.value)) &&
      decoder.some(property => property.name === 'kIsPlatformVideoDecoder' && property.value === 'true');
    const report = {status:vaapi ? 'pass' : 'unqualified',
      browser, browser_version:browserVersion.stdout.trim(),
      mode:process.argv.includes('--no-test-flags') ? 'launcher-flags-only' :
        advancedVaapi ? 'nvidia-vaapi-advanced-flags' :
        nvidiaVaapi ? 'nvidia-vaapi-flags' : 'default-vaapi-flag',
      flags:launchFlags, fixture:`generated ${codec} ${size} 24 fps ${seconds} seconds`,
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
