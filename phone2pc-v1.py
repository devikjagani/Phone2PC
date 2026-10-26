#!/usr/bin/env python3
"""
phone2pc - send photos & videos from your phone straight to your PC over Wi-Fi.

Run on the PC:      python phone2pc.py
Open on the phone:  the http://<pc-ip>:8000 address printed in the terminal.

No dependencies (Python 3.8+ standard library only). Files are streamed to disk,
so multi-GB videos are fine. Everything stays on your local network.

Options:
  --dir  PATH   where files are saved   (default: ./MobileUploads)
  --port N      port to listen on       (default: 8000)
  --pin  CODE   set your own PIN        (default: random 4 digits)
  --no-pin      disable the PIN (trusted network only)
"""
import argparse, json, mimetypes, os, random, re, socket, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

ARGS = None
ROOT = None
PIN = None
CHUNK = 1024 * 1024

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phone → PC</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#14181f;--mut:#667085;--acc:#2563eb;--ok:#16a34a;--err:#dc2626;--bd:#e4e7ec}
@media (prefers-color-scheme:dark){:root{--bg:#0e1116;--card:#171b22;--fg:#e8ecf2;--mut:#8b94a3;--acc:#4f8bff;--bd:#2a313c}}
*{box-sizing:border-box}body{margin:0;font:16px/1.4 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:720px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0 16px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:16px;margin-bottom:16px}
.drop{border:2px dashed var(--bd);border-radius:12px;padding:28px 12px;text-align:center;color:var(--mut)}
.drop.over{border-color:var(--acc);color:var(--acc)}
button,.btn{background:var(--acc);color:#fff;border:0;border-radius:10px;padding:12px 18px;font-size:16px;font-weight:600;cursor:pointer;display:inline-block}
button.sec{background:transparent;color:var(--acc);border:1px solid var(--bd)}
input[type=password],input[type=text]{width:100%;padding:12px;border-radius:10px;border:1px solid var(--bd);background:var(--bg);color:var(--fg);font-size:18px;letter-spacing:4px;text-align:center}
.row{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;justify-content:center}
.item{padding:10px 0;border-top:1px solid var(--bd)}.item:first-child{border-top:0}
.nm{display:flex;justify-content:space-between;gap:8px;font-size:14px;word-break:break-all}
.st{color:var(--mut);white-space:nowrap}
.bar{height:6px;background:var(--bd);border-radius:3px;margin-top:6px;overflow:hidden}
.bar i{display:block;height:100%;width:0;background:var(--acc);transition:width .15s}
.done .bar i{background:var(--ok)}.fail .bar i{background:var(--err)}.fail .st{color:var(--err)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px}
.grid a{position:relative;display:block;aspect-ratio:1;border-radius:10px;overflow:hidden;background:var(--bd)}
.grid img,.grid video{width:100%;height:100%;object-fit:cover}
.grid span{position:absolute;left:0;right:0;bottom:0;font-size:10px;padding:2px 5px;background:rgba(0,0,0,.55);color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hide{display:none}.mut{color:var(--mut);font-size:14px}
</style></head><body><main>
<h1>📱 → 💻 Phone to PC</h1>

<div id="login" class="card hide">
  <p>Enter the PIN shown in the PC terminal.</p>
  <input id="pin" type="password" inputmode="numeric" autocomplete="off" placeholder="PIN">
  <div class="row"><button id="go">Connect</button></div>
  <p id="lerr" class="mut" style="color:var(--err);text-align:center"></p>
</div>

<div id="app" class="hide">
  <div class="card">
    <div id="drop" class="drop">
      <div>Tap to choose photos &amp; videos<span class="hide" id="dd"> — or drop them here</span></div>
      <div class="row">
        <label class="btn">Select files<input id="file" type="file" accept="image/*,video/*" multiple hidden></label>
      </div>
    </div>
    <div id="queue"></div>
  </div>

  <div class="card">
    <div class="nm" style="margin-bottom:10px"><b>Saved on PC</b><span id="count" class="mut"></span></div>
    <div id="grid" class="grid"></div>
    <p id="empty" class="mut hide">Nothing here yet.</p>
  </div>
</div>
</main>
<script>
const $=s=>document.querySelector(s);
let pin=localStorage.getItem('p2p_pin')||'';
const hdr=()=>({'X-Pin':pin});
const fmt=b=>b>1e9?(b/1e9).toFixed(2)+' GB':b>1e6?(b/1e6).toFixed(1)+' MB':Math.max(1,Math.round(b/1e3))+' KB';
const q=s=>encodeURIComponent(s);

async function api(path){const r=await fetch(path,{headers:hdr()});if(r.status===401)throw 401;return r.json();}

async function start(){
  try{
    const cfg=await (await fetch('/api/config')).json();
    if(!cfg.pin){pin='';return show();}
    await api('/api/files');show();
  }catch(e){$('#login').classList.remove('hide');$('#app').classList.add('hide');}
}
function show(){$('#login').classList.add('hide');$('#app').classList.remove('hide');load();}
$('#go').onclick=async()=>{
  pin=$('#pin').value.trim();
  try{await api('/api/files');localStorage.setItem('p2p_pin',pin);$('#lerr').textContent='';show();}
  catch(e){$('#lerr').textContent='Wrong PIN';}
};

async function load(){
  const files=await api('/api/files');
  const g=$('#grid');g.innerHTML='';
  $('#count').textContent=files.length+' file'+(files.length===1?'':'s');
  $('#empty').classList.toggle('hide',files.length>0);
  for(const f of files){
    const url='/files/'+q(f.name)+'?pin='+q(pin);
    const a=document.createElement('a');a.href=url;a.target='_blank';
    const isVid=/^video\//.test(f.type);
    const m=document.createElement(isVid?'video':'img');
    m.src=isVid?url+'#t=0.1':url;if(isVid){m.preload='metadata';m.muted=true;}else{m.loading='lazy';}
    const s=document.createElement('span');s.textContent=(isVid?'▶ ':'')+f.name+' · '+fmt(f.size);
    a.append(m,s);g.append(a);
  }
}

function upload(file){
  return new Promise(res=>{
    const el=document.createElement('div');el.className='item';
    el.innerHTML='<div class="nm"><span></span><span class="st">0%</span></div><div class="bar"><i></i></div>';
    el.querySelector('span').textContent=file.name+' ('+fmt(file.size)+')';
    $('#queue').prepend(el);
    const st=el.querySelector('.st'),bar=el.querySelector('i');
    const x=new XMLHttpRequest();
    x.open('PUT','/upload?name='+q(file.name)+'&mtime='+(file.lastModified||0));
    x.setRequestHeader('X-Pin',pin);
    x.upload.onprogress=e=>{if(e.lengthComputable){const p=Math.round(e.loaded/e.total*100);st.textContent=p+'%';bar.style.width=p+'%';}};
    x.onload=()=>{if(x.status===200){el.classList.add('done');st.textContent='Saved ✓';bar.style.width='100%';}else{el.classList.add('fail');st.textContent='Failed ('+x.status+')';}res();};
    x.onerror=()=>{el.classList.add('fail');st.textContent='Network error';res();};
    x.send(file);
  });
}
async function handle(list){
  for(const f of [...list]) await upload(f);   // one at a time = reliable on phones
  load();
}
$('#file').onchange=e=>{handle(e.target.files);e.target.value='';};
const d=$('#drop');
if(window.matchMedia('(hover:hover)').matches)$('#dd').classList.remove('hide');
['dragover','dragenter'].forEach(t=>d.addEventListener(t,e=>{e.preventDefault();d.classList.add('over');}));
['dragleave','drop'].forEach(t=>d.addEventListener(t,e=>{e.preventDefault();d.classList.remove('over');}));
d.addEventListener('drop',e=>handle(e.dataTransfer.files));
start();
</script></body></html>"""


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def safe_name(name):
    name = os.path.basename(unquote(name).replace("\\", "/"))
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    return name or f"upload_{int(time.time())}"


def unique_path(name):
    base, ext = os.path.splitext(name)
    path, i = os.path.join(ROOT, name), 1
    while os.path.exists(path):
        path = os.path.join(ROOT, f"{base} ({i}){ext}")
        i += 1
    return path


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "phone2pc"

    def log_message(self, fmt, *a):
        pass

    # ---- helpers
    def send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def authed(self, qs):
        if not PIN:
            return True
        given = self.headers.get("X-Pin") or (qs.get("pin") or [""])[0]
        return given == PIN

    # ---- routes
    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/":
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/config":
            return self.send(200, json.dumps({"pin": bool(PIN)}), "application/json")
        if not self.authed(qs):
            return self.send(401, "PIN required")
        if u.path == "/api/files":
            out = []
            for n in os.listdir(ROOT):
                p = os.path.join(ROOT, n)
                if os.path.isfile(p) and not n.endswith(".part"):
                    t = mimetypes.guess_type(n)[0] or "application/octet-stream"
                    st = os.stat(p)
                    out.append({"name": n, "size": st.st_size, "type": t, "mtime": st.st_mtime})
            out.sort(key=lambda f: f["mtime"], reverse=True)
            return self.send(200, json.dumps(out), "application/json")
        if u.path.startswith("/files/"):
            return self.serve_file(safe_name(u.path[7:]))
        self.send(404, "Not found")

    do_HEAD = do_GET

    def serve_file(self, name):
        p = os.path.join(ROOT, name)
        if not os.path.isfile(p):
            return self.send(404, "Not found")
        size = os.path.getsize(p)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                return self.send(416, "", extra={"Content-Range": f"bytes */{size}"})
            code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(p, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    buf = f.read(min(CHUNK, left))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    left -= len(buf)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_PUT(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path != "/upload":
            return self.send(404, "Not found")
        if not self.authed(qs):
            return self.send(401, "PIN required")
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length < 0:
            return self.send(411, "Content-Length required")
        name = safe_name((qs.get("name") or [""])[0])
        dest = unique_path(name)
        tmp = dest + ".part"
        got = 0
        try:
            with open(tmp, "wb") as f:
                while got < length:
                    buf = self.rfile.read(min(CHUNK, length - got))
                    if not buf:
                        break
                    f.write(buf)
                    got += len(buf)
            if got != length:
                os.remove(tmp)
                self.close_connection = True
                return
            os.replace(tmp, dest)
            try:  # keep the original photo/video date
                mt = int((qs.get("mtime") or ["0"])[0]) / 1000
                if mt > 0:
                    os.utime(dest, (mt, mt))
            except Exception:
                pass
            print(f"  ✓ {os.path.basename(dest)}  ({got/1e6:.1f} MB)")
            self.send(200, json.dumps({"saved": os.path.basename(dest)}), "application/json")
        except Exception as e:
            print("  ✗ upload failed:", e)
            try:
                os.remove(tmp)
            except OSError:
                pass
            self.close_connection = True


def main():
    global ARGS, ROOT, PIN
    ap = argparse.ArgumentParser(description="Send phone photos/videos to this PC over Wi-Fi")
    ap.add_argument("--dir", default="MobileUploads")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--pin")
    ap.add_argument("--no-pin", action="store_true")
    ARGS = ap.parse_args()
    ROOT = os.path.abspath(ARGS.dir)
    os.makedirs(ROOT, exist_ok=True)
    PIN = None if ARGS.no_pin else (ARGS.pin or f"{random.randint(0, 9999):04d}")

    ip = lan_ip()
    print("\n  Phone → PC is running")
    print(f"  Saving to : {ROOT}")
    print(f"  Open on phone (same Wi-Fi): http://{ip}:{ARGS.port}")
    print(f"  PIN       : {PIN if PIN else '(disabled)'}")
    print("  Press Ctrl+C to stop.\n")
    try:
        ThreadingHTTPServer(("0.0.0.0", ARGS.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
