#!/usr/bin/env python3
"""
phone2pc v2 - two-way file, folder, zip and text sharing between phone and PC.

Run on the PC:        python phone2pc.py
Open on any device:   the http://<pc-ip>:8000 address printed in the terminal
                      (on the PC itself use http://localhost:8000 - no PIN needed).

Python 3.8+, standard library only. Everything stays on your local network.

Options:
  --dir PATH   shared folder             (default: ./MobileUploads)
  --port N     port                      (default: 8000)
  --pin CODE   your own PIN              (default: random 4 digits)
  --no-pin     disable the PIN
  --https      HTTPS with a self-signed certificate (needs `openssl` on PATH);
               lets phones keep the screen awake during long uploads
"""
import argparse, hmac, json, mimetypes, os, random, re, shutil, socket, ssl
import subprocess, sys, threading, time, uuid, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote, quote

ROOT = META = TFILE = PIN = None
CHUNK = 1 << 20
RESERVED = ".p2p"
TLOCK = threading.Lock()
UID = re.compile(r"^[0-9a-f]{8,64}$")
NOZIP = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp4", ".mov", ".mkv",
         ".avi", ".webm", ".zip", ".7z", ".rar", ".gz", ".mp3", ".m4a", ".aac"}

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phone ⇄ PC</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#14181f;--mut:#667085;--acc:#2563eb;--ok:#16a34a;--err:#dc2626;--bd:#e4e7ec}
@media (prefers-color-scheme:dark){:root{--bg:#0e1116;--card:#171b22;--fg:#e8ecf2;--mut:#8b94a3;--acc:#4f8bff;--bd:#2a313c}}
*{box-sizing:border-box}body{margin:0;font:16px/1.4 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:760px;margin:0 auto;padding:14px}
h1{font-size:20px;margin:6px 0 12px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:14px;margin-bottom:14px}
button,.btn{background:var(--acc);color:#fff;border:0;border-radius:10px;padding:10px 16px;font:600 15px system-ui;cursor:pointer;display:inline-block;text-decoration:none}
button.sec{background:transparent;color:var(--acc);border:1px solid var(--bd)}
.sm{padding:6px 10px;font-size:13px}.x{background:none;color:var(--mut);padding:0 4px}
input[type=password],textarea,select{width:100%;padding:10px;border-radius:10px;border:1px solid var(--bd);background:var(--bg);color:var(--fg);font:16px system-ui}
input[type=password]{font-size:18px;letter-spacing:4px;text-align:center}
textarea{resize:vertical}select{width:auto}
.tabs{display:flex;gap:8px;margin-bottom:14px}.tabs button{flex:1;background:var(--card);color:var(--fg);border:1px solid var(--bd)}
.tabs button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.row.c{justify-content:center}
.drop{border:2px dashed var(--bd);border-radius:12px;padding:18px 10px;text-align:center;color:var(--mut)}
.drop.over{border-color:var(--acc);color:var(--acc)}
.item{padding:8px 0;border-top:1px solid var(--bd)}
.nm{display:flex;justify-content:space-between;gap:8px;font-size:14px;word-break:break-all;align-items:center}
.st{color:var(--mut);white-space:nowrap;margin-left:auto}
.bar{height:5px;background:var(--bd);border-radius:3px;margin-top:5px;overflow:hidden}
.bar i{display:block;height:100%;width:0;background:var(--acc);transition:width .15s}
.done .bar i{background:var(--ok)}.fail .bar i,.fail .st{background:none;color:var(--err)}.fail .bar i{background:var(--err)}
.file{display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--bd)}
.file:first-child{border-top:0}
.th{width:44px;height:44px;border-radius:8px;background:var(--bd);display:flex;align-items:center;justify-content:center;font-size:22px;overflow:hidden;flex:none}
.th img{width:100%;height:100%;object-fit:cover}
.fi{flex:1;min-width:0}.fi a{color:var(--fg);text-decoration:none;font-weight:600;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer}
.mut{color:var(--mut);font-size:13px}
#crumbs a{color:var(--acc);cursor:pointer}
#selbar{position:sticky;bottom:8px;background:var(--card);border:1px solid var(--acc);border-radius:12px;padding:8px 12px;margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.snip{border-top:1px solid var(--bd);padding:10px 0}.snip pre{white-space:pre-wrap;word-break:break-word;margin:6px 0;font:14px/1.4 ui-monospace,monospace;max-height:180px;overflow:auto}
#toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#111;color:#fff;padding:8px 16px;border-radius:20px;opacity:0;transition:.2s;pointer-events:none}
#toast.on{opacity:.92}.hide{display:none!important}
</style></head><body><main>
<h1>📱 ⇄ 💻 Phone &amp; PC</h1>

<div id="login" class="card hide">
  <p>Enter the PIN shown in the PC terminal.</p>
  <input id="pin" type="password" inputmode="numeric" autocomplete="off" placeholder="PIN">
  <div class="row c" style="margin-top:12px"><button id="go">Connect</button></div>
  <p id="lerr" class="mut" style="color:var(--err);text-align:center"></p>
</div>

<div id="app" class="hide">
<div class="tabs"><button data-tab="files" class="on">Files</button><button data-tab="text">Text</button></div>

<section id="t-files">
  <div class="card">
    <div id="drop" class="drop">
      <div class="row c">
        <label class="btn">📷 Photos &amp; videos<input id="fPhoto" type="file" accept="image/*,video/*" multiple hidden></label>
        <label class="btn">📄 Files<input id="fAny" type="file" multiple hidden></label>
        <label class="btn hide" id="dirBtn">📁 Folder<input id="fDir" type="file" webkitdirectory multiple hidden></label>
      </div>
      <p class="mut" style="margin:10px 0 0"><span id="dd" class="hide">Drop files or whole folders here. </span>Uploads go into the folder you have open below.</p>
    </div>
    <div class="row" style="margin-top:10px">
      <span class="mut">Simultaneous:</span>
      <select id="conc"><option>1</option><option>2</option><option>3</option><option>4</option><option>6</option></select>
      <span id="qs" class="mut"></span>
      <span style="margin-left:auto" class="row"><button id="retry" class="sec sm">Retry failed</button><button id="clr" class="sec sm">Clear finished</button></span>
    </div>
    <p id="hint" class="mut hide">Keep this page open while uploading. Tip: start the server with --https so the screen can stay awake.</p>
    <div id="queue"></div>
  </div>

  <div class="card">
    <div class="row" style="justify-content:space-between">
      <div id="crumbs"></div>
      <span class="row"><button id="mk" class="sec sm">＋ Folder</button><button id="all" class="sec sm">Select all</button></span>
    </div>
    <div id="lib"></div>
    <div id="selbar" class="hide"><b id="sn"></b>
      <a id="sdl" class="btn sm" download>⬇ Download</a>
      <button id="sdel" class="sm sec" style="color:var(--err)">🗑 Delete</button>
      <button id="sclr" class="sm sec">Clear</button></div>
  </div>
</section>

<section id="t-text" class="hide">
  <div class="card">
    <textarea id="tx" rows="4" placeholder="Type or paste text here, then send it to your other device…"></textarea>
    <div class="row" style="margin-top:10px"><button id="tsend">Send</button><button id="tpaste" class="sec">Paste from clipboard</button>
      <button id="tclear" class="sec" style="margin-left:auto;color:var(--err)">Clear all</button></div>
  </div>
  <div class="card"><div id="tl"></div></div>
</section>
</div>
<div id="toast"></div>
</main>
<script>
const $=s=>document.querySelector(s),esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=b=>b>=1e9?(b/1e9).toFixed(2)+' GB':b>=1e6?(b/1e6).toFixed(1)+' MB':b>=1e3?Math.round(b/1e3)+' KB':b+' B';
const sleep=ms=>new Promise(r=>setTimeout(r,ms)),CH=8*1024*1024;
let pin=localStorage.getItem('p2p_pin')||'',cwd='',sel=new Set(),entries=[],texts=[],queue=[],active=0,seq=0,tab='files',lastT='',
    conc=+(localStorage.getItem('p2p_conc')||3);
const dev=/Android|iPhone|iPad|Mobi/i.test(navigator.userAgent)?'Phone':'PC';
const pq=()=>'pin='+encodeURIComponent(pin),ep=p=>p.split('/').map(encodeURIComponent).join('/'),sub=n=>(cwd?cwd+'/':'')+n;
const when=t=>new Date(t*1000).toLocaleString([],{dateStyle:'short',timeStyle:'short'});
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('on');clearTimeout(toast.t);toast.t=setTimeout(()=>t.classList.remove('on'),1600);}
async function j(u,o={}){const r=await fetch(u,{...o,headers:{'X-Pin':pin,...(o.headers||{})}});if(r.status===401)throw 401;
  const b=await r.json().catch(()=>({}));if(!r.ok)throw Object.assign(new Error(b.error||r.status),{status:r.status,body:b});return b;}
const post=(u,b)=>j(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
function h53(s){let a=0xdeadbeef,b=0x41c6ce57;for(let i=0;i<s.length;i++){const c=s.charCodeAt(i);a=Math.imul(a^c,2654435761);b=Math.imul(b^c,1597334677);}
  a=Math.imul(a^(a>>>16),2246822507)^Math.imul(b^(b>>>13),3266489909);b=Math.imul(b^(b>>>16),2246822507)^Math.imul(a^(a>>>13),3266489909);
  return(b>>>0).toString(16).padStart(8,'0')+(a>>>0).toString(16).padStart(8,'0');}

/* ---------- login ---------- */
async function start(){try{const c=await(await fetch('/api/config')).json();if(c.pin)await j('/api/list?path=');enter();}
  catch(e){$('#login').classList.remove('hide');$('#app').classList.add('hide');}}
function enter(){$('#login').classList.add('hide');$('#app').classList.remove('hide');refresh();}
$('#go').onclick=async()=>{pin=$('#pin').value.trim();try{await j('/api/list?path=');localStorage.setItem('p2p_pin',pin);$('#lerr').textContent='';enter();}catch(e){$('#lerr').textContent='Wrong PIN';}};

/* ---------- tabs ---------- */
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;
  document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('on',x===b));
  $('#t-files').classList.toggle('hide',tab!=='files');$('#t-text').classList.toggle('hide',tab!=='text');
  tab==='files'?refresh():loadTexts();});

/* ---------- upload engine: parallel files, chunked + resumable ---------- */
function addFiles(list){for(const {file,path} of list){const full=sub(path);
  const it={id:++seq,file,path:full,sent:0,state:'wait',uid:h53(full+'|'+file.size+'|'+file.lastModified),err:''};queue.push(it);mkEl(it);draw(it);}
  $('#hint').classList.toggle('hide',window.isSecureContext||!queue.length);pump();}
function mkEl(it){const el=document.createElement('div');el.className='item';
  el.innerHTML='<div class="nm"><span class="n"></span><span class="st"></span><button class="x">✕</button></div><div class="bar"><i></i></div>';
  el.querySelector('.n').textContent=it.path+' ('+fmt(it.file.size)+')';el.querySelector('.x').onclick=()=>cancel(it);it.el=el;$('#queue').prepend(el);}
function draw(it){const el=it.el;if(!el)return;const p=it.file.size?Math.min(100,Math.round(it.sent/it.file.size*100)):100;
  el.className='item '+(it.state==='done'?'done':(it.state==='fail'||it.state==='cancel')?'fail':'');
  el.querySelector('i').style.width=(it.state==='done'?100:p)+'%';
  el.querySelector('.st').textContent={wait:'Waiting',up:p+'%',retry:'Retrying…',done:'Saved ✓',fail:it.err||'Failed',cancel:'Cancelled'}[it.state];}
function cancel(it){if(['done','fail','cancel'].includes(it.state))return;it.state='cancel';it.x&&it.x.abort();draw(it);}
function pump(){while(active<conc){const it=queue.find(i=>i.state==='wait');if(!it)break;run(it);}}
async function run(it){it.state='up';active++;wake();draw(it);
  try{let off=0;try{off=(await j('/api/upload/status?uid='+it.uid)).received||0;}catch(e){if(e===401)throw'PIN rejected';}
    if(off>it.file.size)off=0;it.sent=off;
    while(off<it.file.size)off=await chunk(it,off);
    await post('/api/upload/finish',{uid:it.uid,path:it.path,size:it.file.size,mtime:it.file.lastModified||0});
    it.state='done';it.sent=it.file.size;}
  catch(e){if(it.state!=='cancel'){it.state='fail';it.err=typeof e==='string'?e:(e&&e.message)||'Failed';}}
  active--;if(!active)unwake();draw(it);pump();if(!active&&!queue.some(i=>i.state==='wait'))refresh();}
async function chunk(it,off){for(let t=0;;t++){
  if(it.state==='cancel')throw'cancelled';const end=Math.min(off+CH,it.file.size);
  try{return await put(it,off,end);}
  catch(e){if(it.state==='cancel')throw'cancelled';if(e.status===401)throw'PIN rejected';
    if(e.status===409&&e.received!=null){off=e.received;it.sent=off;if(off>=it.file.size)return off;continue;}
    if(t>=8)throw'Network error';it.state='retry';draw(it);await sleep(Math.min(1000*2**t,15000));
    try{off=(await j('/api/upload/status?uid='+it.uid)).received;it.sent=off;if(off>=it.file.size)return off;}catch(_){}
    it.state='up';}}}
function put(it,off,end){return new Promise((res,rej)=>{const x=new XMLHttpRequest();it.x=x;
  x.open('PUT','/api/upload/chunk?uid='+it.uid+'&offset='+off);x.setRequestHeader('X-Pin',pin);
  x.upload.onprogress=e=>{it.sent=off+e.loaded;draw(it);};
  x.onload=()=>{let b={};try{b=JSON.parse(x.responseText)}catch(_){}x.status===200?res(b.received):rej({status:x.status,received:b.received});};
  x.onerror=x.ontimeout=()=>rej({status:0});x.onabort=()=>rej({status:-1});x.send(it.file.slice(off,end));});}
$('#clr').onclick=()=>{queue=queue.filter(i=>{const d=['done','fail','cancel'].includes(i.state);if(d)i.el.remove();return!d;});};
$('#retry').onclick=()=>{queue.forEach(i=>{if(i.state==='fail'||i.state==='cancel'){i.state='wait';i.err='';draw(i);}});pump();};
$('#conc').value=conc;$('#conc').onchange=e=>{conc=+e.target.value;localStorage.setItem('p2p_conc',conc);pump();};
let lb=0;setInterval(()=>{const t=queue.reduce((a,i)=>a+(i.state==='done'?i.file.size:i.sent),0),sp=Math.max(0,t-lb);lb=t;
  const w=queue.filter(i=>i.state==='wait').length;$('#qs').textContent=(active||w)?`${fmt(sp)}/s · ${active} active · ${w} waiting`:'';},1000);
let wl=null;async function wake(){try{if('wakeLock'in navigator&&!wl)wl=await navigator.wakeLock.request('screen');}catch(e){}}
function unwake(){try{wl&&wl.release()}catch(e){}wl=null;}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&active)wake();});
addEventListener('beforeunload',e=>{if(active||queue.some(i=>i.state==='wait')){e.preventDefault();e.returnValue='';}});

/* ---------- pick / drop files & folders ---------- */
for(const id of['fPhoto','fAny','fDir'])$('#'+id).onchange=e=>{addFiles([...e.target.files].map(f=>({file:f,path:f.webkitRelativePath||f.name})));e.target.value='';};
const hover=matchMedia('(hover:hover)').matches;if(hover){$('#dd').classList.remove('hide');$('#dirBtn').classList.remove('hide');}
async function walk(en,pre,out){if(en.isFile){await new Promise(r=>en.file(f=>{out.push({file:f,path:pre+en.name});r();},r));}
  else if(en.isDirectory){const rd=en.createReader();let all=[],b;do{b=await new Promise(r=>rd.readEntries(r,()=>r([])));all.push(...b);}while(b.length);
    for(const c of all)await walk(c,pre+en.name+'/',out);}}
const dz=$('#drop');['dragover','dragenter'].forEach(t=>dz.addEventListener(t,e=>{e.preventDefault();dz.classList.add('over');}));
['dragleave','drop'].forEach(t=>dz.addEventListener(t,e=>{e.preventDefault();dz.classList.remove('over');}));
dz.addEventListener('drop',async e=>{const ens=[...e.dataTransfer.items].map(i=>i.webkitGetAsEntry&&i.webkitGetAsEntry()).filter(Boolean);
  const out=[];for(const en of ens)await walk(en,'',out);addFiles(out);});

/* ---------- library ---------- */
async function refresh(){try{entries=await j('/api/list?path='+encodeURIComponent(cwd));const names=new Set(entries.map(e=>sub(e.name)));
  sel=new Set([...sel].filter(p=>names.has(p)));drawLib();}
  catch(e){if(e===401){$('#login').classList.remove('hide');$('#app').classList.add('hide');}else if(cwd){cwd='';refresh();}}}
const icon=e=>e.dir?'📁':/^video/.test(e.type)?'🎬':/^image/.test(e.type)?'🖼️':/\.(zip|7z|rar|gz|tar)$/i.test(e.name)?'🗜️':'📄';
function drawLib(){let acc='';$('#crumbs').innerHTML='<a data-go="">Home</a>'+cwd.split('/').filter(Boolean).map(s=>{acc+=(acc?'/':'')+s;return` / <a data-go="${esc(acc)}">${esc(s)}</a>`;}).join('');
  $('#lib').innerHTML=entries.length?entries.map(e=>{const r=sub(e.name),th=(!e.dir&&/^image\//.test(e.type)&&e.size<6e6)?`<img loading="lazy" src="/files/${ep(r)}?${pq()}">`:icon(e);
    const nm=e.dir?`<a data-go="${esc(r)}">${esc(e.name)}</a>`:`<a target="_blank" href="/files/${ep(r)}?${pq()}">${esc(e.name)}</a>`;
    const dl=e.dir?`/zip?p=${encodeURIComponent(r)}&${pq()}`:`/dl/${ep(r)}?${pq()}`;
    return`<div class="file"><input type="checkbox" data-sel="${esc(r)}" ${sel.has(r)?'checked':''}><div class="th">${th}</div>
      <div class="fi">${nm}<div class="mut">${e.dir?'Folder':fmt(e.size)} · ${when(e.mtime)}</div></div>
      ${/\.zip$/i.test(e.name)?`<button class="sec sm" data-unzip="${esc(r)}">Unzip</button>`:''}
      <a class="btn sm" href="${dl}" download>⬇${e.dir?' ZIP':''}</a></div>`;}).join(''):'<p class="mut">This folder is empty.</p>';
  drawSel();}
function drawSel(){const n=sel.size,b=$('#selbar');b.classList.toggle('hide',!n);if(!n)return;$('#sn').textContent=n+' selected';
  const a=[...sel],one=a.length===1&&entries.find(e=>sub(e.name)===a[0]&&!e.dir);
  $('#sdl').href=one?`/dl/${ep(a[0])}?${pq()}`:`/zip?${a.map(p=>'p='+encodeURIComponent(p)).join('&')}&${pq()}`;
  $('#sdl').textContent=one?'⬇ Download':'⬇ Download as ZIP';}
document.addEventListener('click',async e=>{const g=e.target.closest('[data-go]');if(g){e.preventDefault();cwd=g.dataset.go;sel.clear();refresh();return;}
  const u=e.target.closest('[data-unzip]');if(u){u.disabled=true;toast('Extracting…');try{await post('/api/extract',{path:u.dataset.unzip});toast('Extracted');}catch(x){toast('Extract failed');}refresh();}});
document.addEventListener('change',e=>{const s=e.target.dataset&&e.target.dataset.sel;if(s!==undefined&&s!==''){e.target.checked?sel.add(s):sel.delete(s);drawSel();}});
$('#all').onclick=()=>{if(sel.size===entries.length)sel.clear();else entries.forEach(e=>sel.add(sub(e.name)));drawLib();};
$('#sclr').onclick=()=>{sel.clear();drawLib();};
$('#sdel').onclick=async()=>{if(!confirm(`Delete ${sel.size} item(s) from the PC? This cannot be undone.`))return;await post('/api/delete',{paths:[...sel]});sel.clear();refresh();};
$('#mk').onclick=async()=>{const n=prompt('New folder name');if(!n)return;try{await post('/api/mkdir',{path:sub(n)});}catch(e){toast('Could not create folder');}refresh();};

/* ---------- shared text ---------- */
async function loadTexts(){try{const t=await j('/api/texts'),s=JSON.stringify(t);if(s===lastT)return;lastT=s;texts=t;
  $('#tl').innerHTML=t.length?t.map(x=>`<div class="snip"><div class="mut">${esc(x.device)} · ${when(x.ts)}</div><pre>${esc(x.text)}</pre>
    <div class="row"><button class="sm" data-copy="${x.id}">Copy</button><button class="sm sec" data-tdel="${x.id}">Delete</button></div></div>`).join(''):'<p class="mut">Nothing shared yet. Send some text from either device.</p>';}catch(e){}}
async function copy(t){try{await navigator.clipboard.writeText(t);}catch(e){const a=document.createElement('textarea');a.value=t;a.style.cssText='position:fixed;opacity:0';
  document.body.append(a);a.focus();a.select();try{document.execCommand('copy')}catch(_){}a.remove();}toast('Copied');}
document.addEventListener('click',async e=>{const c=e.target.closest('[data-copy]');if(c){const x=texts.find(t=>t.id===c.dataset.copy);x&&copy(x.text);}
  const d=e.target.closest('[data-tdel]');if(d){await post('/api/texts/delete',{id:d.dataset.tdel});lastT='';loadTexts();}});
$('#tsend').onclick=async()=>{const v=$('#tx').value;if(!v.trim())return;await post('/api/texts',{text:v,device:dev});$('#tx').value='';lastT='';loadTexts();toast('Sent');};
$('#tpaste').onclick=async()=>{try{$('#tx').value=await navigator.clipboard.readText();}catch(e){toast('Long-press the box and choose Paste');$('#tx').focus();}};
$('#tclear').onclick=async()=>{if(!confirm('Delete all shared text?'))return;await post('/api/texts/delete',{all:true});lastT='';loadTexts();};
setInterval(()=>{if(document.hidden||$('#app').classList.contains('hide'))return;tab==='text'?loadTexts():(active||refresh());},3000);
start();
</script></body></html>"""


# ------------------------------------------------------------------ helpers
def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def clean(part):
    part = re.sub(r'[<>:"|?*\x00-\x1f\\]', "_", part).strip().rstrip(" .")
    return part


def rel_clean(rel):
    """Sanitise a relative path: no '..', no absolute paths, no reserved folder."""
    parts = [clean(p) for p in str(rel).replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in (".", "..")]
    if parts and parts[0].lower() == RESERVED:
        parts[0] = "_" + parts[0]
    return "/".join(parts)


def abspath(rel):
    return os.path.join(ROOT, *rel.split("/")) if rel else ROOT


def to_rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def unique_path(folder, name, is_dir=False):
    base, ext = (name, "") if is_dir else os.path.splitext(name)
    path, i = os.path.join(folder, name), 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({i}){ext}")
        i += 1
    return path


def part_path(uid):
    return os.path.join(META, "partial", uid + ".part")


def list_dir(d):
    out = []
    for n in os.listdir(d):
        if n.startswith("."):
            continue
        p = os.path.join(d, n)
        try:
            st = os.stat(p)
        except OSError:
            continue
        isd = os.path.isdir(p)
        out.append({"name": n, "dir": isd, "size": 0 if isd else st.st_size, "mtime": st.st_mtime,
                    "type": "" if isd else (mimetypes.guess_type(n)[0] or "")})
    out.sort(key=lambda e: (not e["dir"], -e["mtime"]))
    return out


def texts_get():
    try:
        with open(TFILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def texts_save(items):
    tmp = TFILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f)
    os.replace(tmp, TFILE)


class ChunkOut:
    """File-like wrapper that writes HTTP/1.1 chunked data (lets us stream a ZIP)."""
    def __init__(self, w):
        self.w = w

    def write(self, b):
        if b:
            self.w.write(b"%x\r\n" % len(b) + bytes(b) + b"\r\n")
        return len(b)

    def flush(self):
        self.w.flush()


def zip_add_file(zf, p, arc):
    zi = zipfile.ZipInfo.from_file(p, arc, strict_timestamps=False)
    zi.compress_type = zipfile.ZIP_STORED if os.path.splitext(p)[1].lower() in NOZIP else zipfile.ZIP_DEFLATED
    with open(p, "rb") as src, zf.open(zi, "w", force_zip64=True) as dst:
        shutil.copyfileobj(src, dst, CHUNK)


def zip_add_dir(zf, top, arc):
    for cur, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        files = [f for f in files if not f.startswith(".")]
        base = arc + ("/" + os.path.relpath(cur, top).replace(os.sep, "/") if cur != top else "")
        if not dirs and not files:
            zi = zipfile.ZipInfo(base + "/")
            zi.external_attr = (0o40775 << 16) | 0x10
            zf.writestr(zi, b"")
        for f in files:
            zip_add_file(zf, os.path.join(cur, f), base + "/" + f)


# ------------------------------------------------------------------ server
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "phone2pc"

    def log_message(self, *a):
        pass

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
        self.wfile.write(body)

    def json_out(self, obj, code=200, extra=None):
        self.send(code, json.dumps(obj), "application/json", extra)

    def is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def authed(self, qs):
        if not PIN or self.is_local():
            return True
        given = self.headers.get("X-Pin") or (qs.get("pin") or [""])[0]
        return hmac.compare_digest(given.encode(), PIN.encode())

    def body_json(self, limit=2_500_000):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def drain(self, n):
        while n > 0:
            buf = self.rfile.read(min(CHUNK, n))
            if not buf:
                break
            n -= len(buf)

    def handle_any(self):
        try:
            self.route()
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            self.close_connection = True
        except Exception as e:
            print("  ! error:", repr(e))
            try:
                self.json_out({"error": str(e)}, 500)
            except Exception:
                self.close_connection = True

    do_GET = do_POST = do_PUT = handle_any

    # ---- routing
    def route(self):
        u = urlparse(self.path)
        qs, p, m = parse_qs(u.query), u.path, self.command
        q1 = lambda k, d="": (qs.get(k) or [d])[0]
        if m == "GET" and p == "/":
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if m == "GET" and p == "/api/config":
            return self.json_out({"pin": bool(PIN) and not self.is_local()})
        body = None
        if m == "POST":
            body = self.body_json() if self.authed(qs) else None
        if not self.authed(qs):
            self.close_connection = True
            return self.json_out({"error": "PIN required"}, 401, {"Connection": "close"})

        if m == "GET":
            if p == "/api/list":
                d = abspath(rel_clean(q1("path")))
                if not os.path.isdir(d):
                    return self.json_out({"error": "no such folder"}, 404)
                return self.json_out(list_dir(d))
            if p == "/api/texts":
                return self.json_out(texts_get())
            if p == "/api/upload/status":
                uid = q1("uid")
                if not UID.match(uid):
                    return self.json_out({"error": "bad uid"}, 400)
                pp = part_path(uid)
                return self.json_out({"received": os.path.getsize(pp) if os.path.exists(pp) else 0})
            if p.startswith("/files/"):
                return self.serve_file(rel_clean(unquote(p[7:])), False)
            if p.startswith("/dl/"):
                return self.serve_file(rel_clean(unquote(p[4:])), True)
            if p == "/zip":
                return self.serve_zip(qs.get("p", []))
        elif m == "PUT" and p == "/api/upload/chunk":
            return self.upload_chunk(qs)
        elif m == "POST":
            if p == "/api/upload/finish":
                return self.upload_finish(body)
            if p == "/api/texts":
                text = str(body.get("text", ""))[:200000]
                if not text.strip():
                    return self.json_out({"error": "empty"}, 400)
                with TLOCK:
                    items = texts_get()
                    items.insert(0, {"id": uuid.uuid4().hex[:10], "text": text, "ts": time.time(),
                                     "device": str(body.get("device", "Device"))[:24]})
                    texts_save(items[:200])
                return self.json_out({"ok": True})
            if p == "/api/texts/delete":
                with TLOCK:
                    items = [] if body.get("all") else [t for t in texts_get() if t["id"] != body.get("id")]
                    texts_save(items)
                return self.json_out({"ok": True})
            if p == "/api/delete":
                for r in body.get("paths", []):
                    r = rel_clean(r)
                    t = abspath(r)
                    if not r or not os.path.lexists(t):
                        continue
                    if os.path.isdir(t) and not os.path.islink(t):
                        shutil.rmtree(t)
                    else:
                        os.remove(t)
                return self.json_out({"ok": True})
            if p == "/api/mkdir":
                r = rel_clean(body.get("path", ""))
                if not r:
                    return self.json_out({"error": "bad name"}, 400)
                os.makedirs(abspath(r), exist_ok=True)
                return self.json_out({"ok": True})
            if p == "/api/extract":
                return self.extract(rel_clean(body.get("path", "")))
        return self.json_out({"error": "not found"}, 404)

    # ---- uploads: resumable, chunked
    def upload_chunk(self, qs):
        uid = (qs.get("uid") or [""])[0]
        if not UID.match(uid):
            return self.json_out({"error": "bad uid"}, 400)
        try:
            off = int((qs.get("offset") or ["0"])[0])
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            return self.json_out({"error": "bad request"}, 400)
        if length < 0:
            return self.json_out({"error": "Content-Length required"}, 411)
        pp = part_path(uid)
        os.makedirs(os.path.dirname(pp), exist_ok=True)
        cur = os.path.getsize(pp) if os.path.exists(pp) else 0
        if off != cur:
            self.drain(length)
            return self.json_out({"error": "offset mismatch", "received": cur}, 409)
        got = 0
        with open(pp, "r+b" if cur else "wb") as f:
            f.seek(cur)
            while got < length:
                buf = self.rfile.read(min(CHUNK, length - got))
                if not buf:
                    break
                f.write(buf)
                got += len(buf)
            if got != length:
                f.truncate(cur)
                self.close_connection = True
                return
        self.json_out({"received": cur + got})

    def upload_finish(self, b):
        uid = str(b.get("uid", ""))
        if not UID.match(uid):
            return self.json_out({"error": "bad uid"}, 400)
        size = int(b.get("size", 0))
        parts = rel_clean(b.get("path", "")).split("/")
        name = parts[-1] or f"upload_{int(time.time())}"
        folder = abspath("/".join(parts[:-1]))
        pp = part_path(uid)
        have = os.path.getsize(pp) if os.path.exists(pp) else 0
        if size > 0 and have != size:
            return self.json_out({"error": "incomplete", "received": have}, 409)
        os.makedirs(folder, exist_ok=True)
        dest = unique_path(folder, name)
        if size == 0:
            open(dest, "wb").close()
        else:
            shutil.move(pp, dest)
        try:
            mt = int(b.get("mtime", 0)) / 1000
            if mt > 0:
                os.utime(dest, (mt, mt))
        except Exception:
            pass
        print(f"  ✓ {to_rel(dest)}  ({size/1e6:.1f} MB)")
        self.json_out({"saved": to_rel(dest)})

    # ---- downloads
    def serve_file(self, rel, attach):
        p = abspath(rel)
        if not rel or not os.path.isfile(p):
            return self.json_out({"error": "not found"}, 404)
        size, name = os.path.getsize(p), os.path.basename(p)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
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
        if attach:
            fb = name.encode("ascii", "replace").decode().replace('"', "_")
            self.send_header("Content-Disposition", f"attachment; filename=\"{fb}\"; filename*=UTF-8''{quote(name)}")
        self.end_headers()
        with open(p, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                buf = f.read(min(CHUNK, left))
                if not buf:
                    break
                self.wfile.write(buf)
                left -= len(buf)

    def serve_zip(self, rels):
        items = []
        for r in rels:
            r = rel_clean(r)
            if r and os.path.exists(abspath(r)):
                items.append(abspath(r))
        if not items:
            return self.json_out({"error": "nothing to zip"}, 404)
        zname = (os.path.basename(items[0]) if len(items) == 1 else "selection") + ".zip"
        fb = zname.encode("ascii", "replace").decode().replace('"', "_")
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Content-Disposition", f"attachment; filename=\"{fb}\"; filename*=UTF-8''{quote(zname)}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with zipfile.ZipFile(ChunkOut(self.wfile), "w", allowZip64=True) as zf:
            for p in items:
                base = os.path.basename(p)
                zip_add_dir(zf, p, base) if os.path.isdir(p) else zip_add_file(zf, p, base)
        self.wfile.write(b"0\r\n\r\n")

    def extract(self, rel):
        p = abspath(rel)
        if not rel or not os.path.isfile(p) or not zipfile.is_zipfile(p):
            return self.json_out({"error": "not a zip file"}, 400)
        stem = clean(os.path.splitext(os.path.basename(p))[0]) or "extracted"
        out = unique_path(os.path.dirname(p), stem, is_dir=True)
        os.makedirs(out)
        with zipfile.ZipFile(p) as zf:
            for zi in zf.infolist():
                r = rel_clean(zi.filename)  # drops '..' => no zip-slip
                if not r:
                    continue
                dest = os.path.join(out, *r.split("/"))
                if zi.is_dir():
                    os.makedirs(dest, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(zi) as s, open(dest, "wb") as d:
                    shutil.copyfileobj(s, d, CHUNK)
        self.json_out({"folder": to_rel(out)})


def make_cert(ip):
    cert, key = os.path.join(META, f"cert-{ip}.pem"), os.path.join(META, f"key-{ip}.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
                        "-days", "825", "-subj", "/CN=phone2pc", "-addext",
                        f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return cert, key


def main():
    global ROOT, META, TFILE, PIN
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Two-way file/text sharing between phone and PC")
    ap.add_argument("--dir", default="MobileUploads")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--pin")
    ap.add_argument("--no-pin", action="store_true")
    ap.add_argument("--https", action="store_true")
    a = ap.parse_args()
    ROOT = os.path.abspath(a.dir)
    META = os.path.join(ROOT, RESERVED)
    TFILE = os.path.join(META, "texts.json")
    os.makedirs(os.path.join(META, "partial"), exist_ok=True)
    PIN = None if a.no_pin else (a.pin or f"{random.randint(0, 9999):04d}")

    ip = lan_ip()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    scheme = "http"
    if a.https:
        try:
            cert, key = make_cert(ip)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            srv.socket = ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
            scheme = "https"
        except (FileNotFoundError, subprocess.CalledProcessError):
            print("  ! HTTPS needs `openssl` on PATH - continuing with plain HTTP.")
    print("\n  Phone ⇄ PC is running")
    print(f"  Shared folder : {ROOT}")
    print(f"  On this PC    : {scheme}://localhost:{a.port}   (no PIN needed)")
    print(f"  On your phone : {scheme}://{ip}:{a.port}   (same Wi-Fi)")
    print(f"  PIN           : {PIN if PIN else '(disabled)'}")
    if scheme == "https":
        print("  (the browser will warn about the self-signed certificate - accept it once)")
    print("  Press Ctrl+C to stop.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
