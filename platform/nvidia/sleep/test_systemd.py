#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Mock VT commands in three real user-systemd transactions; no physical sleep."""
from pathlib import Path
import importlib.util,json,os,subprocess,time
H=Path(__file__).resolve().parent
assert os.geteuid()!=0, 'Run only against the invoking user manager; never PID 1'
spec=importlib.util.spec_from_file_location('vt',H/'test_vt.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
units=Path(os.environ['XDG_RUNTIME_DIR'])/'systemd/user';units.mkdir(parents=True,exist_ok=True);results=[]
def run(*args,check=True):return subprocess.run(['/usr/bin/systemctl','--user',*args],text=True,capture_output=True,timeout=15,check=check)
for case in ('normal','prepare-error','sleep-error'):
 t=v.VTTests();t.setUp();root=t.root;name='n1x-vt-regression-'+str(os.getpid())+'-'+case;vt=name+'-prepare.service';parent=name+'-sleep.service';files=[]
 try:
  source=(H/'nvidia-notifier-vt.service').read_text();source=source.replace('Before=systemd-suspend.service','Before='+parent).replace('/usr/libexec/nvidia-notifier-vt',str(t.script)).replace('RuntimeDirectory=nvidia-notifier-vt','RuntimeDirectory='+name)
  source+='\nEnvironment=MOCK_VT_ROOT='+str(root)+'\n'
  path=units/vt;path.write_text(source);files.append(path)
  path=units/parent;path.write_text('[Unit]\nDefaultDependencies=no\nRequires='+vt+'\nAfter='+vt+'\n[Service]\nType=oneshot\nExecStart=/usr/bin/bash -c "echo sleep >> '+str(root/'log')+';exit '+('1' if case=='sleep-error' else '0')+'"\n');files.append(path)
  if case=='prepare-error':(root/'fail').touch()
  run('daemon-reload');started=run('start',parent,check=False)
  for i in range(50):
   state=run('show',vt,'-p','ActiveState','--value').stdout.strip()
   if state in ('inactive','failed'):break
   time.sleep(.1)
  log=(root/'log').read_text();assert state in ('inactive','failed'),state
  assert ('sleep\n' in log)==(case!='prepare-error'),log
  assert started.returncode==0 if case=='normal' else started.returncode!=0
  assert (root/'vt').read_text()=='1\n'
  assert not (root/'console').exists()
  if case!='prepare-error':assert log=='switch 63\nsleep\nswitch 1\n',repr(log)
  results.append({'case':case,'passed':True,'log':log,'real_vt_changed':False,'sleep_executed':False})
 finally:
  run('stop',parent,vt,check=False);run('reset-failed',parent,vt,check=False)
  for f in files:f.unlink()
  run('daemon-reload');t.doCleanups()
print(json.dumps(results,indent=2))
