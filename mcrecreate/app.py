"""Servidor local + ventana. Pipeline: links -> fotogramas -> COLMAP -> voxeles -> bloques."""
import base64, json, os, shutil, sys, threading, time, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import numpy as np
from . import core

FROZEN = getattr(sys, "frozen", False)
BASE = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parents[1]
WEB = Path(getattr(sys, "_MEIPASS", BASE)) / "mcrecreate" / "web"
PROJ = BASE / "proyecto"
PAL = ["#%02x%02x%02x" % c for c in core.PALETTE.values()]
TOOLS = ("ffmpeg", "colmap", "yt-dlp")


def setup_path():
    extra = []
    for exe in ("colmap.exe", "ffmpeg.exe", "yt-dlp.exe"):
        for f in (BASE / "tools").rglob(exe):
            extra.append(str(f.parent)); break
    os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "")])


def clean(d, *names):
    for n in names:
        p = d / n
        if p.is_dir(): shutil.rmtree(p, ignore_errors=True)
        elif p.exists(): p.unlink()


class State:
    def __init__(s):
        s.items, s.n, s.log, s.busy, s.o = {}, 0, [], False, {}
        s.items["comb"] = s.new("comb", "Escena combinada", PROJ / "combinado", use=False)
        core.LOG = s.addlog

    def new(s, k, src, d, use=True):
        return dict(id=k, src=src, every=1.0, stream=0, up="-y", start="", end="", use=use, status="—" if k == "comb" else "nuevo",
                    raw=None, ver=0, dir=d, fkey=None)

    def addlog(s, l):
        if l.startswith("[download]") and s.log and s.log[-1].startswith("[download]"): s.log[-1] = l
        else: s.log.append(l)

    def st(s, k, t): s.items[k]["status"] = t

    def snapshot(s, since):
        return dict(items=[dict(id=k, src=i["src"], every=i["every"], stream=i["stream"], up=i["up"], start=i["start"], end=i["end"], use=i["use"],
                                status=i["status"], has=i["raw"] is not None, ver=i["ver"]) for k, i in sorted(s.items.items(), key=lambda kv: kv[0] == "comb")],
                    log=s.log[since:], logn=len(s.log), busy=s.busy, miss=[t for t in TOOLS if not shutil.which(t)])

    # ---- pipeline ----
    def frames_for(s, k):
        it = s.items[k]; d = it["dir"]; d.mkdir(parents=True, exist_ok=True)
        key = (it["src"], it["every"], it["stream"], s.o["max"], it["start"].strip(), it["end"].strip())
        if it["fkey"] == key and (d / "images").exists(): return d / "images"
        if it["fkey"] and (it["fkey"][0], it["fkey"][2], it["fkey"][4], it["fkey"][5]) != (key[0], key[2], key[4], key[5]): clean(d, "video0.mp4")
        clean(d, "images", "sparse", "dense", "db.db", "cloud.ply")
        s.st(k, "descargando…")
        core.get_frames([it["src"]], d, it["every"], it["stream"], key[3], key[4], key[5])
        it["fkey"] = key
        return d / "images"

    def run_one(s, k):
        it = s.items[k]; fr = s.frames_for(k)
        clean(it["dir"], "sparse", "dense", "db.db", "cloud.ply"); s.st(k, "reconstruyendo…")
        it["raw"] = core.load_ply(core.reconstruct(it["dir"], fr, s.o["dense"], False)); it["ver"] += 1

    def run_comb(s):
        used = [k for k, i in s.items.items() if k != "comb" and i["use"]]
        if not used: raise RuntimeError("Marca al menos un link con ✓")
        c = s.items["comb"]; d = c["dir"]
        clean(d, "images", "sparse", "dense", "db.db", "cloud.ply"); (d / "images").mkdir(parents=True, exist_ok=True)
        for k in used:
            for f in s.frames_for(k).glob("*.jpg"): shutil.copy(f, d / "images" / f"{k}_{f.name}")
        s.st("comb", "reconstruyendo…")
        c["raw"] = core.load_ply(core.reconstruct(d, d / "images", s.o["dense"], True)); c["ver"] += 1

    def process(s, k, mx, dense):
        if s.busy: raise RuntimeError("Ya hay un proceso en curso")
        s.busy, s.o = True, dict(max=mx, dense=dense)
        def w():
            try:
                s.run_comb() if k == "comb" else s.run_one(k); s.st(k, "listo ✓")
            except (SystemExit, Exception) as e:
                s.st(k, "error"); s.addlog("ERROR: " + (str(e) or repr(e)))
            finally: s.busy = False
        threading.Thread(target=w, daemon=True).start()

    def voxels(s, k, size, fill):
        it = s.items[k]; pts, col = it["raw"]
        v, c, shape = core.voxelize(core.orient(pts, it["up"]), col, size)
        if fill > 0: v, c = core.fill_gaps(v, c, shape, fill)
        return v, core.to_blocks(c), shape

    def act(s, name, d):
        if name == "add":
            ids = []
            for src in d["srcs"]:
                s.n += 1; k = f"i{s.n}"; ids.append(k)
                s.items[k] = s.new(k, src, PROJ / f"link{s.n}")
            return dict(ids=ids)
        if name == "clipboard":
            import subprocess
            for cmd in (["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], ["pbpaste"], ["wl-paste"],
                        ["xclip", "-o", "-selection", "clipboard"]):
                try:
                    t = subprocess.check_output(cmd, text=True, timeout=5, stderr=subprocess.DEVNULL,
                                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).strip()
                    return dict(text=t)
                except Exception: continue
            return dict(text="", error="No pude leer el portapapeles")
        if name == "remove": s.items.pop(d["id"], None)
        elif name == "update":
            it = s.items[d["id"]]
            for f in ("every", "stream", "up", "use", "start", "end"):
                if f in d: it[f] = d[f]
        elif name == "process": s.process(d["id"], int(d["max"]), bool(d["dense"]))
        elif name == "export":
            v, b, sh = s.voxels(d["id"], int(d["size"]), int(d["fill"]))
            out = PROJ / "exports"; out.mkdir(parents=True, exist_ok=True); nm = time.strftime("mundo_%Y%m%d_%H%M%S")
            core.export_schem(out / f"{nm}.schem", v, b, sh); core.export_mcfunction(out / f"{nm}.mcfunction", v, b)
            try: os.startfile(out)
            except Exception: pass
            return dict(path=str(out))
        return dict(ok=True)


ST = None


class H(BaseHTTPRequestHandler):
    def log_message(s, *a): pass

    def reply(s, body, ct="application/json", code=200):
        body = body if isinstance(body, bytes) else json.dumps(body).encode()
        s.send_response(code); s.send_header("Content-Type", ct); s.send_header("Cache-Control", "no-store"); s.send_header("Content-Length", str(len(body))); s.end_headers()
        s.wfile.write(body)

    def do_GET(s):
        u = urlparse(s.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/": return s.reply((WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/state": return s.reply(ST.snapshot(int(q.get("log", 0))))
            if u.path == "/api/voxels":
                v, b, sh = ST.voxels(q["id"], int(q["size"]), int(q["fill"]))
                arr = np.column_stack([v, b]).astype("<i2")
                return s.reply(dict(data=base64.b64encode(arr.tobytes()).decode(), n=len(v), shape=[int(x) for x in sh], pal=PAL))
            s.reply({"error": "not found"}, code=404)
        except Exception as e: s.reply({"error": str(e)}, code=500)

    def do_POST(s):
        try:
            d = json.loads(s.rfile.read(int(s.headers.get("Content-Length", 0))) or b"{}")
            s.reply(ST.act(s.path[5:], d))
        except Exception as e: s.reply({"error": str(e)}, code=500)


def main():
    global ST
    setup_path(); ST = State()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        import webview
        webview.create_window("Minecraft Recreator", url, width=1380, height=860, background_color="#0b0d12", text_select=True)
        webview.start()
    except Exception:
        webbrowser.open(url); print("Abierto en", url, "(Ctrl+C para salir)")
        try: threading.Event().wait()
        except KeyboardInterrupt: pass
