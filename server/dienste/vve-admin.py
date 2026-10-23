#!/usr/bin/env python3
import json, subprocess, os, threading, uuid, time
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = open("/etc/vve/admin.token").read().strip()
JOBS = {}

def run_job(jid, cmd):
    JOBS[jid]["state"] = "running"
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3600)
        JOBS[jid]["output"] = (p.stdout + p.stderr)[-4000:]
        JOBS[jid]["rc"] = p.returncode
        JOBS[jid]["state"] = "done" if p.returncode == 0 else "failed"
    except Exception as e:
        JOBS[jid]["output"] = str(e)
        JOBS[jid]["state"] = "failed"
    JOBS[jid]["finished"] = time.time()

def start(cmd, label):
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"id": jid, "label": label, "state": "queued", "started": time.time(), "output": ""}
    threading.Thread(target=run_job, args=(jid, cmd), daemon=True).start()
    return {"job": jid, "label": label}

class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _auth(self):
        if self.headers.get("X-Cockpit-Token", "") != TOKEN:
            self._send({"error": "unauthorized"}, 401)
            return False
        return True

    def do_GET(self):
        if not self._auth(): return
        if self.path.startswith("/rgb"):
            try:
                z = open("/etc/vve/rgb.state").read().strip()
            except Exception:
                z = "on"
            return self._send({"rgb": z})
        if self.path.startswith("/jobs/"):
            jid = self.path.split("/")[-1]
            return self._send(JOBS.get(jid, {"error": "unknown job"}))
        if self.path.startswith("/jobs"):
            return self._send(list(JOBS.values()))
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        if not self._auth(): return
        ln = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(ln) or "{}") if ln else {}
        p = self.path.rstrip("/")

        if p == "/rgb/on":
            open("/etc/vve/rgb.state", "w").write("on")
            return self._send({"rgb": "on"})
        if p == "/rgb/off":
            open("/etc/vve/rgb.state", "w").write("off")
            return self._send({"rgb": "off"})
        if p == "/apt/check":
            return self._send(start("sudo apt-get update", "apt update"))
        if p == "/apt/upgrade":
            return self._send(start("sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get -y upgrade", "apt upgrade"))
        if p == "/model/pull":
            n = body.get("name", "")
            if not n.replace(":", "").replace("-", "").replace(".", "").replace("_", "").replace("/", "").isalnum():
                return self._send({"error": "invalid model name"}, 400)
            return self._send(start(f"ollama pull {n}", f"pull {n}"))
        if p == "/model/rm":
            n = body.get("name", "")
            if not n.replace(":", "").replace("-", "").replace(".", "").replace("_", "").replace("/", "").isalnum():
                return self._send({"error": "invalid model name"}, 400)
            return self._send(start(f"ollama rm {n}", f"rm {n}"))
        # Server neu starten (28.09.2026, Veikos Wunsch: ein Knopf dafuer im
        # Cockpit). Frueher bewusst NICHT angeboten ("wer neu startet, sollte
        # dabeisitzen") — die Rueckfrage im Cockpit traegt das jetzt, und sie
        # warnt, wenn gerade ein Auftrag laeuft. sudoers erlaubt genau
        # /usr/sbin/reboot ohne Argumente; die kurze Pause davor laesst diese
        # Antwort noch zum Browser durch, bevor die Verbindung wegfaellt.
        if p == "/system/reboot":
            return self._send(start("sleep 4; sudo -n /usr/sbin/reboot", "Server-Neustart"))
        if p == "/service/restart":
            s = body.get("name", "")
            if s not in ("ollama", "caddy"):
                return self._send({"error": "service not allowed"}, 400)
            return self._send(start(f"sudo systemctl restart {s}", f"restart {s}"))
        self._send({"error": "not found"}, 404)

    def log_message(self, *a):
        pass

HTTPServer(("127.0.0.1", 9098), H).serve_forever()
