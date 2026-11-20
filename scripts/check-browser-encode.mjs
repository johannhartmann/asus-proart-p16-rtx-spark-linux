#!/usr/bin/env node
// Verify a real H.264 WebRTC sender with an isolated Chrome profile and VA driver.
import {spawn, spawnSync} from 'node:child_process';
import {createServer} from 'node:http';
import {mkdtemp, readdir, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const output = process.argv[2];
const driverPath = process.argv.find(arg => arg.startsWith('--driver-path='))?.slice(14);
const gatePath = process.argv.find(arg => arg.startsWith('--gate='))?.slice(7);
const installedGate = process.argv.find(arg => arg.startsWith('--installed-gate='))?.slice(17);
const headless = process.argv.includes('--headless');
const browser = process.argv.find(arg => arg.startsWith('--browser='))?.slice(10) ?? '/usr/bin/google-chrome-stable';
const profile = process.argv.find(arg => arg.startsWith('--profile='))?.slice(10) ?? 'high';
if (!['high', 'baseline'].includes(profile)) throw Error(`Invalid profile ${profile}`);
if (!output || !driverPath || (installedGate && (gatePath || !/^[a-p]{32}$/.test(installedGate)))) {
  console.error('Usage: node scripts/check-browser-encode.mjs RESULT.json --driver-path=/absolute/build/dir [--gate=/absolute/codec-gate.js | --installed-gate=EXTENSION_ID] [--browser=/absolute/chrome] [--headless]');
  process.exit(2);
}
const version = spawnSync(browser, ['--version'], {encoding:'utf8', timeout:5000});
if (version.status !== 0) throw Error(`${browser} --version failed`);
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const temp = await mkdtemp(join(tmpdir(), 'p16-browser-encode-'));
  const html = `<!doctype html><video id="remote" autoplay muted playsinline></video><script>
window.runEncodeTest = async () => {
  const manualPreference = ${!gatePath && !installedGate};
  const canvas = document.createElement('canvas');
  canvas.width = 640; canvas.height = 360;
  const ctx = canvas.getContext('2d');
  let frame = 0;
  const paint = () => {
    ctx.fillStyle = frame++ % 2 ? '#ff4820' : '#006be6';
    ctx.fillRect(0, 0, 640, 360);
    ctx.fillStyle = 'white'; ctx.fillRect((frame * 11) % 560, 120, 80, 80);
  };
  paint();
  const timer = setInterval(paint, 33);
  const stream = canvas.captureStream(30);
  const sender = new RTCPeerConnection();
  const receiver = new RTCPeerConnection();
  try {
    sender.onicecandidate = e => e.candidate && receiver.addIceCandidate(e.candidate);
    receiver.onicecandidate = e => e.candidate && sender.addIceCandidate(e.candidate);
    receiver.ontrack = e => { document.getElementById('remote').srcObject = e.streams[0]; };
    const transceiver = sender.addTransceiver(stream.getVideoTracks()[0], {direction:'sendonly', streams:[stream]});
    const codecs = RTCRtpSender.getCapabilities('video').codecs;
    const h264 = codecs.filter(codec => codec.mimeType.toLowerCase() === 'video/h264');
    if (!h264.length) throw Error('Chrome offers no H.264 WebRTC codec');
    h264.sort((a, b) => Number(/profile-level-id=${profile === 'high' ? '6400' : '42e0'}/i.test(b.sdpFmtpLine ?? '')) -
                        Number(/profile-level-id=${profile === 'high' ? '6400' : '42e0'}/i.test(a.sdpFmtpLine ?? '')));
    if (manualPreference) transceiver.setCodecPreferences(h264);
    await sender.setLocalDescription(await sender.createOffer());
    await receiver.setRemoteDescription(sender.localDescription);
    await receiver.setLocalDescription(await receiver.createAnswer());
    await sender.setRemoteDescription(receiver.localDescription);
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(Error('ICE connection timeout')), 10000);
      const check = () => {
        if (sender.connectionState === 'connected') { clearTimeout(timeout); resolve(); }
      };
      sender.onconnectionstatechange = check; check();
    });
    await new Promise(resolve => setTimeout(resolve, 5000));
    const stats = await transceiver.sender.getStats();
    const outbound = [...stats.values()].find(item => item.type === 'outbound-rtp' && item.kind === 'video');
    const codec = outbound && stats.get(outbound.codecId);
    const receiverStats = await receiver.getStats();
    const inbound = [...receiverStats.values()].find(item => item.type === 'inbound-rtp' && item.kind === 'video');
    return {offeredH264:h264.map(item => item.sdpFmtpLine),
      codecGate:window.__p16MeetH264CodecGate?.counters,
      outbound: outbound && {framesEncoded:outbound.framesEncoded, framesSent:outbound.framesSent,
        encoderImplementation:outbound.encoderImplementation, powerEfficientEncoder:outbound.powerEfficientEncoder,
        totalEncodeTime:outbound.totalEncodeTime, frameWidth:outbound.frameWidth, frameHeight:outbound.frameHeight},
      codec:codec && {mimeType:codec.mimeType, sdpFmtpLine:codec.sdpFmtpLine},
      framesReceived:inbound?.framesReceived, framesDecoded:inbound?.framesDecoded,
      remoteWidth:document.getElementById('remote').videoWidth};
  } finally {
    clearInterval(timer); stream.getTracks().forEach(track => track.stop());
    sender.close(); receiver.close();
  }
};
</script>`;
const server = createServer((_request, response) => {
  response.writeHead(200, {'content-type':'text/html; charset=utf-8'});
  response.end(html);
});
let chrome;
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const flags = ['AcceleratedVideoEncoder', 'VaapiOnNvidiaGPUs', 'VaapiIgnoreDriverChecks'];
  chrome = spawn(browser, [
    `--user-data-dir=${temp}`, '--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0', '--no-first-run',
    ...(headless ? ['--headless'] : []),
    ...(installedGate ? [] : ['--disable-extensions', `--enable-features=${flags.join(',')}`,
      '--ignore-gpu-blocklist', '--use-gl=angle', '--use-angle=gl', '--ozone-platform=wayland']),
    '--enable-logging=stderr', '--vmodule=vaapi*=3,gpu_video_encode_accelerator_factory*=3,rtc_video_encoder*=3',
    'about:blank',
  ], {stdio:['ignore', 'ignore', 'pipe'], env:{...process.env,
    LIBVA_DRIVER_NAME:'nvidia_vulkan', LIBVA_DRIVERS_PATH:driverPath,
    VKVV_ENABLE_ENCODE:'1', VKVV_LOG:'1'}});
  let stderr = '';
  chrome.stderr.on('data', chunk => { stderr += chunk; });
  let port;
  for (let i = 0; i < 100; i++) {
    try { port = Number((await readFile(join(temp, 'DevToolsActivePort'), 'utf8')).split('\n')[0]); break; }
    catch { await delay(100); }
  }
  if (!port) throw Error('Chrome DevTools port did not open');
  if (installedGate) {
    const path = join(temp, 'Default', 'Extensions', installedGate);
    let versions = [];
    for (let i = 0; i < 100 && !versions.length; i++) {
      versions = await readdir(path).catch(error => {
        if (error.code !== 'ENOENT') throw error;
        return [];
      });
      if (!versions.length) await delay(100);
    }
    if (!versions.length) throw Error('Chrome did not install the external codec gate');
  }
  const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const ws = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  const pending = new Map();
  let id = 0;
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  ws.onmessage = event => {
    const reply = JSON.parse(event.data);
    if (pending.has(reply.id)) { pending.get(reply.id)(reply); pending.delete(reply.id); }
    if (reply.method === 'Fetch.requestPaused') {
      const {requestId} = reply.params;
      void request('Fetch.fulfillRequest', {requestId, responseCode:200,
        responseHeaders:[{name:'content-type', value:'text/html; charset=utf-8'}],
        body:Buffer.from(html).toString('base64')});
    }
  };
  const request = (method, params = {}) => new Promise(resolve => {
    const number = ++id; pending.set(number, resolve);
    ws.send(JSON.stringify({id:number,method,params}));
  });
  try {
    if (gatePath) {
      await request('Page.enable');
      const injection = await request('Page.addScriptToEvaluateOnNewDocument', {
        source:await readFile(gatePath, 'utf8'),
      });
      if (injection.error) throw Error(JSON.stringify(injection.error));
    }
    let url = `http://127.0.0.1:${server.address().port}/`;
    if (installedGate) {
      // Serve the test HTML at the extension's real match origin without
      // contacting Meet. Chrome must inject its installed content script.
      url = 'https://meet.google.com/p16-codec-test';
      const interception = await request('Fetch.enable', {patterns:[{urlPattern:url}]});
      if (interception.error) throw Error(JSON.stringify(interception.error));
    }
    await request('Page.navigate', {url});
    await delay(500);
    const result = await Promise.race([
      request('Runtime.evaluate', {expression:'window.runEncodeTest()', awaitPromise:true, returnByValue:true}),
      new Promise((_, reject) => setTimeout(() => reject(Error('WebRTC encode timeout')), 22000)),
    ]);
    const values = result.result?.result?.value;
    if (result.error || result.result?.exceptionDetails || !values) {
      throw Error(JSON.stringify(result.error || result.result?.exceptionDetails || result));
    }
    const hardwareSubmissions = (stderr.match(/submitted H\.264 Vulkan encode:/g) ?? []).length;
    const encoderErrors = (stderr.match(/NotifyErrorStatus\(|Failed to end picture encode issue/g) ?? []).length;
    const hardware = (!installedGate || values.codecGate?.applied > 0) &&
      values.outbound?.framesEncoded > 30 && values.framesReceived > 30 &&
      values.framesDecoded > 30 && values.remoteWidth === 640 &&
      hardwareSubmissions >= values.outbound.framesEncoded * 0.9 && encoderErrors === 0;
    const report = {status:hardware ? 'pass' : 'unqualified', browser_version:version.stdout.trim(),
      driver_path:driverPath, ...(installedGate ? {installed_gate:true} : {flags}), ...values,
      hardware_submissions:hardwareSubmissions, browser_encoder_errors:encoderErrors,
      driver_log:stderr.split('\n').filter(line =>
        /vaapi_video_encode_accelerator|NotifyError|software_fallback|submitted H\.264 Vulkan encode|captured H\.264 encode|ERROR|H\.264 encode .*failed/i.test(line)).slice(-120)};
    await writeFile(output, JSON.stringify(report, null, 2) + '\n');
    console.log(`${report.status}: ${values.outbound?.framesEncoded ?? 0} WebRTC frames, ${hardwareSubmissions} Vulkan encode submissions`);
    if (!hardware) process.exitCode = 1;
  } finally { ws.close(); }
} finally {
  chrome?.kill('SIGTERM'); server.close(); await delay(300);
  if (chrome?.exitCode === null) chrome.kill('SIGKILL');
  await rm(temp, {recursive:true,force:true});
}
