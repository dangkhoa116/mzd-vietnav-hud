#!/usr/bin/env python3
"""Frida hook runner: attach to a PID on the remote iPhone and stream
script console output to a log file. Survives independently of any CLI.

Usage: python vm_hook_runner.py <pid> <script.js> <out.log>
"""
import os
import sys
import time

import frida

HOST = "192.168.68.172:27043"


def main():
    pid = int(sys.argv[1])
    script_path = sys.argv[2]
    out_path = sys.argv[3]

    out = open(out_path, "a", encoding="utf-8", buffering=1)

    def log(line):
        print(line, file=out, flush=True)

    dev = frida.get_device_manager().add_remote_device(HOST)
    session = dev.attach(pid)
    code = open(script_path, encoding="utf-8").read()
    # The python runtime has no bundled ObjC bridge; splice in frida_tools'
    # and export it globally, exactly like the CLI repl agent does.
    import frida_tools
    bridge = os.path.join(os.path.dirname(frida_tools.__file__), "bridges", "objc.js")
    code = open(bridge, encoding="utf-8").read() + "\nglobalThis.ObjC = bridge;\n" + code
    # console.log messages don't reach python's on_message in this frida
    # version; reroute them through send() instead.
    code = "console.log = function () { send(Array.prototype.join.call(arguments, ' ')); };\n" + code
    script = session.create_script(code)

    def on_message(message, data):
        if message.get("type") == "send":
            log(str(message.get("payload")))
        elif message.get("type") == "log":
            log(message.get("payload", ""))
        elif message.get("type") == "error":
            log("[script-error] " + message.get("description", ""))

    script.on("message", on_message)
    script.load()
    log(f"=== runner attached to pid {pid}, streaming to {out_path} ===")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            script.unload()
        except Exception:
            pass


if __name__ == "__main__":
    main()
