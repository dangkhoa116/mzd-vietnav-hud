#!/usr/bin/env python3
"""Supervisor: giu hooks luon gan vao Runner (VietMap) PID hien hanh.
Moi khi app bi kill va CarPlay relaunch, supervisor tu gan lai trong ~5s.
Usage: python vm_supervisor.py <script.js> <out.log>
"""
import subprocess, sys, time
import frida

HOST = "192.168.68.172:27043"
script_path, out_log = sys.argv[1], sys.argv[2]
child = None
cur_pid = None

def runner_pid():
    try:
        dev = frida.get_device_manager().add_remote_device(HOST)
        for p in dev.enumerate_processes():
            if p.name == 'Runner':
                return p.pid
    except Exception:
        pass
    return None

while True:
    pid = runner_pid()
    if pid and pid != cur_pid:
        if child:
            child.terminate()
            try: child.wait(5)
            except Exception: child.kill()
        with open(out_log, 'a', encoding='utf-8') as f:
            f.write(f"=== supervisor: attach {pid} @ {time.strftime('%H:%M:%S')} ===\n")
        child = subprocess.Popen([sys.executable, 'vm_hook_runner.py', str(pid), script_path, out_log])
        cur_pid = pid
        print(f'attached {pid}', flush=True)
    elif child and child.poll() is not None:
        # runner chet theo process cu — cho gan lai PID moi round sau
        cur_pid = None
    time.sleep(5)
