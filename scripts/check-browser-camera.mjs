#!/usr/bin/env node
// Exercise the real P16 RGB camera through Chromium getUserMedia. No pixels persist.
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const output = process.argv[2];
if (!output) {
  console.error('Usage: node scripts/check-browser-camera.mjs RESULT.json [--graphical-permission] [--browser=chromium|google-chrome-stable]');
  process.exit(2);
}
const graphicalPermission = process.argv.includes('--graphical-permission');
const browser = process.argv.find(arg => arg.startsWith('--browser='))?.split('=', 2)[1] ?? 'chromium';

const html = `<!doctype html><video id="preview" autoplay playsinline muted></video><script>
window.mediaResult = (async () => {
  const stream = await navigator.mediaDevices.getUserMedia({video:{width:1280,height:720,frameRate:30},audio:false});
  const video = document.getElementById('preview');
  video.srcObject = stream;
  await video.play();
  const track = stream.getVideoTracks()[0];
  const settings = track.getSettings();
  const devices = await navigator.mediaDevices.enumerateDevices();
  const selectedLabel = devices.find(d => d.deviceId === settings.deviceId)?.label;
  const canvas = document.createElement('canvas');
  canvas.width = 64; canvas.height = 36;
  const context = canvas.getContext('2d', {willReadFrequently:true});
  const means = [];
  try {
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(Error('30-frame timeout')), 12000);
      const next = () => video.requestVideoFrameCallback(() => {
        context.drawImage(video, 0, 0, 64, 36);
        const pixels = context.getImageData(0, 0, 64, 36).data;
        let sum = 0;
        for (let i = 0; i < pixels.length; i += 4) sum += (pixels[i] + pixels[i+1] + pixels[i+2]) / 3;
        means.push(sum / (pixels.length / 4));
        if (means.length === 30) { clearTimeout(timeout); resolve(); } else next();
      });
      next();
    });
    return {selectedLabel, width:settings.width, height:settings.height,
      frameRate:settings.frameRate, frames:means.length,
      meanMin:Math.min(...means), meanMax:Math.max(...means)};
  } finally { stream.getTracks().forEach(t => t.stop()); }
})().catch(error => ({error:String(error)}));
</script>`;

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const temp = await mkdtemp(join(tmpdir(), 'n1x-browser-camera-'));
const server = createServer((_, response) => {
  response.writeHead(200, {'content-type':'text/html; charset=utf-8'});
  response.end(html);
});
let chromium;
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const pagePort = server.address().port;
  chromium = spawn(browser, [
    ...(!graphicalPermission ? ['--headless=new', '--use-fake-ui-for-media-stream'] :
      ['--ozone-platform=wayland', '--window-size=900,650']),
    `--user-data-dir=${temp}`, '--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0',
    '--no-first-run', '--disable-extensions', 'about:blank',
  ], {stdio:'ignore'});
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
  let id = 0;
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
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
    await request('Page.navigate', {url:`http://127.0.0.1:${pagePort}/`});
    await delay(500);
    let reply;
    let timeoutHandle;
    try {
      reply = await Promise.race([
        request('Runtime.evaluate', {expression:'window.mediaResult',awaitPromise:true,returnByValue:true}),
        new Promise((_, reject) => {
          timeoutHandle = setTimeout(() => reject(Error(`${browser} camera test timed out`)),
            graphicalPermission ? 75000 : 15000);
        }),
      ]);
    } catch (error) {
      await writeFile(output, JSON.stringify({status:'fail', browser,
        method:graphicalPermission ? 'graphical getUserMedia permission' :
          'headless getUserMedia', reason:String(error),
        retained_camera_pixels:false}, null, 2) + '\n');
      throw error;
    } finally {
      clearTimeout(timeoutHandle);
    }
    const result = reply.result?.result?.value;
    if (reply.error || reply.result?.exceptionDetails || result?.error) {
      throw Error(JSON.stringify(reply.error || reply.result?.exceptionDetails || result));
    }
    const accepted = result.selectedLabel === 'ASUS FHD webcam' &&
      result.width === 1280 && result.height === 720 &&
      result.frameRate === 30 && result.frames === 30 &&
      result.meanMax - result.meanMin > 1;
    const report = {status:accepted ? 'pass' : 'fail', browser,
      method:graphicalPermission ?
        'getUserMedia, real V4L2 device, graphical permission and preview' :
        'getUserMedia, real V4L2 device, headless WebRTC preview',
      camera:result, note:graphicalPermission ?
        'Real browser permission UI; no fake media device or retained frame' :
        'Fake permission UI only; no fake media device or retained frame'};
    await writeFile(output, JSON.stringify(report, null, 2) + '\n');
    console.log(`${report.status}: ${result.selectedLabel}, ${result.frames} frames`);
    if (!accepted) process.exitCode = 1;
  } finally { ws.close(); }
} finally {
  chromium?.kill('SIGTERM');
  server.close();
  await delay(300);
  if (chromium?.exitCode === null) chromium.kill('SIGKILL');
  await rm(temp, {recursive:true,force:true});
}
