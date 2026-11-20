#!/usr/bin/env node
// Keep a local Chrome DevTools pipe open so branded Chrome can run the
// Meet-only unpacked codec gate. Chrome 137+ ignores --load-extension.
import {spawn} from 'node:child_process';
import {readdir, readFile} from 'node:fs/promises';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const extensionPath = join(here, 'meet-h264-codec');
const profile = process.argv.find(arg => arg.startsWith('--profile='))?.slice(10);
const driverPath = process.argv.find(arg => arg.startsWith('--driver-dir='))?.slice(13);
const urls = process.argv.filter(arg => !arg.startsWith('--profile=') &&
  !arg.startsWith('--driver-dir=')).slice(2);
const meetUrls = urls.length ? urls : ['https://meet.google.com/'];
const chromePath = '/usr/bin/google-chrome-stable';
if (!profile || !driverPath) throw Error('Missing --profile or --driver-dir');

const manifest = JSON.parse(await readFile(join(extensionPath, 'manifest.json'), 'utf8'));
if (!manifest.content_scripts?.some(script =>
  script.world === 'MAIN' && script.run_at === 'document_start' &&
  script.matches?.includes('https://meet.google.com/*'))) {
  throw Error('Meet H.264 codec gate manifest is invalid');
}

// A second invocation may open another tab in the existing protected profile.
// Refuse to reuse an older Chrome instance that lacks the codec gate.
for (const pid of await readdir('/proc')) {
  if (!/^\d+$/.test(pid)) continue;
  let argv;
  try { argv = (await readFile(`/proc/${pid}/cmdline`)).toString().split('\0'); }
  catch { continue; }
  // The Omarchy Chrome wrapper sometimes passes all flags in one argv entry.
  const command = argv.join(' ');
  if (!argv[0]?.includes('/chrome') ||
      !command.includes(`--user-data-dir=${profile}`) ||
      command.includes('--type=')) continue;
  if (!command.includes('--remote-debugging-pipe') ||
      !command.includes('--enable-unsafe-extension-debugging')) {
    throw Error('Close the older p16-meet-chrome window before using the codec gate');
  }
  const opener = spawn(chromePath, [`--user-data-dir=${profile}`, ...meetUrls], {
    stdio:'ignore', detached:true,
  });
  opener.unref();
  process.exit(0);
}

const features = [
  'AcceleratedVideoEncoder', 'AcceleratedVideoDecodeLinuxGL',
  'VaapiOnNvidiaGPUs', 'VaapiIgnoreDriverChecks', 'VaapiVideoDecoder',
];
const chrome = spawn(chromePath, [
  `--user-data-dir=${profile}`, '--remote-debugging-pipe',
  '--enable-unsafe-extension-debugging', '--no-first-run',
  '--no-default-browser-check', `--enable-features=${features.join(',')}`,
  '--ignore-gpu-blocklist', '--use-gl=angle', '--use-angle=gl',
  '--ozone-platform=wayland', 'about:blank',
], {stdio:['ignore', 'ignore', 'pipe', 'pipe', 'pipe'],
    env:{...process.env, LIBVA_DRIVER_NAME:'nvidia_vulkan',
      LIBVA_DRIVERS_PATH:driverPath, VKVV_ENABLE_ENCODE:'1'}});
let stderr = '';
chrome.stderr.on('data', chunk => {
  stderr = (stderr + chunk.toString()).slice(-20000);
  if (process.env.P16_MEET_VERBOSE === '1') process.stderr.write(chunk);
});
let buffer = Buffer.alloc(0);
let serial = 0;
const pending = new Map();
chrome.stdio[4].on('data', chunk => {
  buffer = Buffer.concat([buffer, chunk]);
  let end;
  while ((end = buffer.indexOf(0)) !== -1) {
    const reply = JSON.parse(buffer.subarray(0, end).toString());
    buffer = buffer.subarray(end + 1);
    if (pending.has(reply.id)) {
      pending.get(reply.id)(reply);
      pending.delete(reply.id);
    }
  }
});
function request(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++serial;
    const timeout = setTimeout(() => {
      pending.delete(id);
      reject(Error(`Chrome ${method} timed out`));
    }, 15000);
    pending.set(id, reply => {
      clearTimeout(timeout);
      if (reply.error) reject(Error(JSON.stringify(reply.error)));
      else resolve(reply.result);
    });
    chrome.stdio[3].write(JSON.stringify({id, method, params}) + '\0');
  });
}
process.on('SIGINT', () => chrome.kill('SIGTERM'));
process.on('SIGTERM', () => chrome.kill('SIGTERM'));

try {
  const version = await request('Browser.getVersion');
  const loaded = await request('Extensions.loadUnpacked', {path:extensionPath});
  const extensions = await request('Extensions.getExtensions');
  if (!extensions.extensions?.some(extension => extension.id === loaded.id)) {
    throw Error('Chrome did not activate the Meet codec gate');
  }
  const before = await request('Target.getTargets');
  const blank = before.targetInfos?.find(target => target.type === 'page' && target.url === 'about:blank');
  for (const url of meetUrls) await request('Target.createTarget', {url});
  if (blank) await request('Target.closeTarget', {targetId:blank.targetId});
  console.error(`P16 Meet H.264 codec gate active (${version.product})`);
  if (chrome.exitCode === null) await new Promise(resolve => chrome.once('exit', resolve));
} catch (error) {
  console.error(`P16 Meet launcher failed: ${error.message}`);
  const lines = stderr.split('\n').filter(line => /extension|ERROR|debugging pipe/i.test(line)).slice(-8);
  if (lines.length) console.error(lines.join('\n'));
  chrome.kill('SIGTERM');
  process.exitCode = 1;
}
