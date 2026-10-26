#!/usr/bin/env python3
"""
Phone2PC - a self-contained desktop app for sharing files, folders, zips and text
between your phone and your PC over your own Wi-Fi.

START IT:   double-click this file (or run `python phone2pc.py`).
            It starts the server and opens its own app window automatically.
            Windows: rename to phone2pc.pyw to hide the console window.

Python 3.8+, standard library only. Nothing leaves your local network.

In the app window press "Connect phone" for a QR code, the address and the PIN.
The PC itself never needs a PIN. Quit from the same panel.

Options (remembered between runs):
  --dir PATH    shared folder            (default: ~/Phone2PC)
  --port N      first port to try        (default: 8000)
  --pin CODE    set a PIN                (default: random 4 digits, saved)
  --no-pin      run without a PIN this time
  --https       self-signed HTTPS (needs `openssl`); lets phones keep the screen awake
  --no-open     don't open the app window automatically
"""
import argparse, hmac, json, mimetypes, os, random, re, shutil, socket, ssl
import subprocess, sys, threading, time, urllib.request, uuid, webbrowser, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote, quote

ROOT = META = TFILE = PIN = SRV = None
PORT, SCHEME = 8000, "http"
CFG_FILE = os.path.join(os.path.expanduser("~"), ".phone2pc.json")
CHUNK = 1 << 20
RESERVED = ".p2p"
TLOCK = threading.Lock()
UID = re.compile(r"^[0-9a-f]{8,64}$")
NOZIP = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".mp4", ".mov", ".mkv",
         ".avi", ".webm", ".zip", ".7z", ".rar", ".gz", ".mp3", ".m4a", ".aac"}

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0a84ff">
<title>Phone2PC</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0' stop-color='%235ac8fa'/%3E%3Cstop offset='1' stop-color='%230a60ff'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='64' height='64' rx='16' fill='url(%23g)'/%3E%3Cpath d='M20 24h24m0 0l-7-7m7 7l-7 7M44 40H20m0 0l7-7m-7 7l7 7' stroke='white' stroke-width='4' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<style>
:root{color-scheme:light dark;--font:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Segoe UI",Inter,Roboto,system-ui,sans-serif;
--fg:#111317;--mut:rgba(60,60,67,.62);--hue:212;--acc:hsl(var(--hue) 100% 52%);--acc2:hsl(var(--hue) 100% 64%);--acc3:hsl(var(--hue) 100% 46%);--ok:var(--acc);--err:#ff453a;
--glass:rgba(255,255,255,.52);--glass2:rgba(255,255,255,.74);--stroke:rgba(255,255,255,.7);--hair:rgba(60,60,67,.14);
--shadow:0 10px 40px rgba(31,38,135,.15);--thumb:rgba(255,255,255,.96);--bg:hsl(var(--hue) 60% 94%);--bg1:hsl(var(--hue) 70% 97%);--bg2:hsl(var(--hue) 55% 89%);--glow:.5;--sl:58%;--sf:.3}
@media (prefers-color-scheme:dark){:root{--fg:#f5f6f8;--mut:rgba(235,235,245,.6);--glass:rgba(38,42,58,.44);--glass2:rgba(52,57,76,.66);
--stroke:rgba(255,255,255,.15);--hair:rgba(255,255,255,.1);--shadow:0 10px 40px rgba(0,0,0,.5);--thumb:rgba(125,132,160,.55);--bg:hsl(var(--hue) 45% 7%);--bg1:hsl(var(--hue) 45% 10%);--bg2:hsl(var(--hue) 50% 5%);--glow:.4;--sl:86%;--sf:.22}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{-webkit-text-size-adjust:100%}
body{margin:0;font:16px/1.4 var(--font);color:var(--fg);background:var(--bg);min-height:100vh;
  padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)}
.bg{position:fixed;inset:0;z-index:-1;background:linear-gradient(160deg,var(--bg1),var(--bg2));overflow:hidden}
.glow{position:absolute;inset:0;background:radial-gradient(150px circle at var(--mx,30%) var(--my,6%),hsl(var(--hue) 100% 72% / calc(var(--glow)*.7)),transparent 72%),radial-gradient(520px circle at var(--mx,30%) var(--my,6%),hsl(var(--hue) 100% 58% / var(--glow)),transparent 72%),radial-gradient(760px circle at 18% -12%,hsl(var(--hue) 100% 60% / calc(var(--glow)*.5)),transparent 70%)}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
main{max-width:820px;margin:0 auto;padding:22px 16px 120px}
.glass{background:radial-gradient(280px circle at var(--lx,50%) var(--ly,0%),hsl(var(--hue) 100% var(--sl) / calc(var(--sa,0)*var(--sf))),transparent 70%),linear-gradient(var(--glass),var(--glass));-webkit-backdrop-filter:blur(26px) saturate(185%);backdrop-filter:blur(26px) saturate(185%);
  border:1px solid var(--stroke);box-shadow:var(--shadow),inset 0 1px 0 rgba(255,255,255,.45),inset 0 -1px 0 rgba(255,255,255,.06);border-radius:24px}
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){.glass{background:var(--glass2)}}
.card{padding:16px;margin-bottom:16px}
.ic{width:18px;height:18px;flex:none;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}.ic.big{width:44px;height:44px;opacity:.55}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:4px 0 20px}
.brand{display:flex;align-items:center;gap:12px}
.logo{width:46px;height:46px;border-radius:15px;display:grid;place-items:center;color:var(--acc)}.logo .ic{width:24px;height:24px}
h1{margin:0;font-size:clamp(26px,5vw,34px);font-weight:700;letter-spacing:-.025em;line-height:1.05}
h2{margin:0 0 4px;font-size:22px;letter-spacing:-.02em}
.mut{color:var(--mut);font-size:13px}p{margin:.4em 0}
button,.btn{font:600 15px/1 var(--font);border:0;border-radius:999px;padding:12px 18px;cursor:pointer;display:inline-flex;align-items:center;gap:8px;color:#fff;text-decoration:none;
  background:linear-gradient(180deg,var(--acc2),var(--acc3));box-shadow:0 6px 18px hsl(var(--hue) 100% 50% / .38),inset 0 1px 0 rgba(255,255,255,.5);transition:transform .18s cubic-bezier(.3,1.4,.5,1),filter .2s}
button:hover,.btn:hover{filter:brightness(1.06)}button:active,.btn:active{transform:scale(.95)}button:disabled{opacity:.5;pointer-events:none}
.glassbtn{color:var(--fg);background:var(--glass2);border:1px solid var(--stroke);box-shadow:inset 0 1px 0 rgba(255,255,255,.45);
  -webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px)}
.danger{color:var(--err)}.sm{padding:9px 14px;font-size:13px}.iconbtn{padding:9px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.row.c{justify-content:center}.sp{margin-left:auto}
input[type=password],textarea,select{font:16px var(--font);color:var(--fg);padding:13px 14px;border-radius:16px;border:1px solid var(--stroke);background:var(--glass2);outline:none;width:100%;
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px)}
input[type=password]{font-size:24px;letter-spacing:10px;text-align:center}textarea{resize:vertical;min-height:96px}
input:focus,textarea:focus,select:focus{border-color:var(--acc);box-shadow:0 0 0 4px hsl(var(--hue) 100% 52% / .22)}
select{width:auto;padding:8px 12px;border-radius:12px;font-size:14px}
.seg{position:relative;display:grid;grid-template-columns:1fr 1fr;padding:4px;border-radius:999px;margin-bottom:18px}
.seg .thumb{position:absolute;top:4px;bottom:4px;left:4px;width:calc(50% - 4px);border-radius:999px;background:var(--thumb);box-shadow:0 3px 10px rgba(0,0,0,.14);transition:transform .45s cubic-bezier(.2,.9,.3,1.15)}
.seg.t1 .thumb{transform:translateX(100%)}
.seg button{position:relative;background:none;box-shadow:none;color:var(--fg);padding:10px;justify-content:center;opacity:.65}.seg button.on{opacity:1}
.drop{border:1.5px dashed var(--hair);border-radius:20px;padding:22px 14px;text-align:center;transition:.25s}
.drop.over{border-color:var(--acc);background:hsl(var(--hue) 100% 52% / .13);transform:scale(1.012)}
.item{padding:10px 12px;border-radius:16px;margin-top:8px;background:var(--glass2);border:1px solid var(--stroke);animation:pop .35s cubic-bezier(.2,.9,.3,1.2)}
@keyframes pop{from{transform:scale(.94);opacity:0}}
.nm{display:flex;gap:8px;font-size:14px;align-items:center}.nm .n{word-break:break-all;flex:1;min-width:0}.st{color:var(--mut);white-space:nowrap;font-size:13px}
.x{background:none;box-shadow:none;color:var(--mut);padding:2px}
.bar{height:6px;border-radius:3px;background:var(--hair);margin-top:7px;overflow:hidden}
.bar i{display:block;height:100%;width:0;border-radius:3px;background:linear-gradient(90deg,var(--acc2),var(--acc3));transition:width .2s}
.done .bar i{background:var(--ok)}.fail .bar i{background:var(--err)}.fail .st{color:var(--err)}.done .st{color:var(--ok)}
.file{display:flex;align-items:center;gap:12px;padding:10px 2px;border-top:1px solid var(--hair)}.file:first-child{border-top:0}
.th{width:48px;height:48px;border-radius:14px;display:grid;place-items:center;color:#fff;overflow:hidden;flex:none;box-shadow:inset 0 1px 0 rgba(255,255,255,.4),0 3px 8px rgba(0,0,0,.15)}
.th img{width:100%;height:100%;object-fit:cover}.th .ic{width:22px;height:22px}
.k-folder,.k-video,.k-image,.k-zip,.k-file{background:linear-gradient(135deg,var(--acc2),var(--acc3))}
.fi{flex:1;min-width:0}.fi a{color:var(--fg);text-decoration:none;font-weight:600;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer}
input[type=checkbox]{appearance:none;-webkit-appearance:none;width:24px;height:24px;border-radius:50%;border:1.7px solid var(--mut);margin:0;flex:none;cursor:pointer;transition:.2s;background:transparent}
input[type=checkbox]:checked{border-color:var(--acc);background:var(--acc) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12.5l4.5 4.5L19 7.5'/%3E%3C/svg%3E") center/15px no-repeat}
#crumbs{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-weight:600}
#crumbs a{cursor:pointer;padding:6px 12px;border-radius:999px;font-size:14px;color:var(--fg)}#crumbs a:last-child{background:var(--glass2);border:1px solid var(--stroke)}
#crumbs>.ic{width:14px;height:14px;opacity:.4}#crumbs a .ic{width:17px;height:17px;display:block}
.empty{text-align:center;padding:34px 10px}.empty p{margin:.3em 0}
.dock{position:fixed;left:50%;bottom:calc(18px + env(safe-area-inset-bottom));transform:translate(-50%,170%);opacity:0;pointer-events:none;z-index:30;
  display:flex;gap:8px;align-items:center;padding:8px 8px 8px 18px;border-radius:999px;transition:transform .5s cubic-bezier(.2,.9,.3,1.12),opacity .3s;white-space:nowrap}
.dock.show{transform:translate(-50%,0);opacity:1;pointer-events:auto}.dock b{font-size:14px;margin-right:4px}
.snip{padding:14px;margin-bottom:12px;animation:pop .35s cubic-bezier(.2,.9,.3,1.2)}
.snip pre{white-space:pre-wrap;word-break:break-word;margin:8px 0 12px;font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;max-height:200px;overflow:auto}
.dev{display:inline-flex;gap:6px;align-items:center;font-size:13px;color:var(--mut)}
.scrim{position:fixed;inset:0;z-index:60;display:flex;align-items:center;justify-content:center;padding:18px;background:rgba(10,12,20,.32);
  -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);opacity:0;pointer-events:none;transition:opacity .3s}
.scrim.show{opacity:1;pointer-events:auto}
.sheet{width:min(430px,100%);max-height:94vh;overflow:auto;padding:22px;transform:translateY(30px) scale(.95);transition:transform .5s cubic-bezier(.2,.9,.3,1.15);background:var(--glass2)}
.scrim.show .sheet{transform:none}
.qr{width:208px;margin:14px auto;padding:10px;background:#fff;border-radius:22px;box-shadow:0 8px 28px rgba(0,0,0,.18)}.qr svg{display:block;width:100%;height:auto;border-radius:10px}
.url{font:600 17px ui-monospace,SFMono-Regular,Menlo,monospace;text-align:center;word-break:break-all;margin:6px 0 12px}
.pin{text-align:center;margin:8px 0}.pin b{display:inline-grid;place-items:center;width:44px;height:54px;margin:0 4px;border-radius:15px;background:var(--glass2);border:1px solid var(--stroke);font-size:26px;font-weight:700}
.pathbox{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all;padding:10px 12px;border-radius:14px;background:var(--glass2);border:1px solid var(--stroke);margin:6px 0 10px}
#toast{position:fixed;left:50%;top:calc(16px + env(safe-area-inset-top));transform:translate(-50%,-90px);z-index:80;padding:11px 20px;border-radius:999px;font-weight:600;font-size:14px;transition:transform .45s cubic-bezier(.2,.9,.3,1.2)}
#toast.on{transform:translate(-50%,0)}.hide{display:none!important}
@media (max-width:520px){main{padding:16px 12px 120px}.lbl{display:none}[data-unzip]{padding:9px}.file .sm{padding:9px 11px}.dock{width:calc(100% - 24px);justify-content:space-between}}
</style></head><body>
<div class="bg"><div class="glow"></div></div>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<symbol id="i-swap" viewBox="0 0 24 24"><path d="M5 8h14m0 0l-4-4m4 4l-4 4M19 16H5m0 0l4-4m-4 4l4 4"/></symbol>
<symbol id="i-phone" viewBox="0 0 24 24"><rect x="7" y="2.5" width="10" height="19" rx="2.8"/><path d="M11 18.5h2"/></symbol>
<symbol id="i-laptop" viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="11" rx="2.2"/><path d="M2 19.5h20"/></symbol>
<symbol id="i-photo" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="3.5"/><circle cx="9" cy="10" r="1.7"/><path d="M21 16l-5-5-8 8"/></symbol>
<symbol id="i-file" viewBox="0 0 24 24"><path d="M7 3h7l5 5v11a2 2 0 01-2 2H7a2 2 0 01-2-2V5a2 2 0 012-2zM14 3v5h5"/></symbol>
<symbol id="i-image" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="3.5"/><circle cx="9" cy="10" r="1.7"/><path d="M21 16l-5-5-8 8"/></symbol>
<symbol id="i-video" viewBox="0 0 24 24"><rect x="3" y="6" width="13" height="12" rx="3"/><path d="M16 10.5l5-3v9l-5-3z"/></symbol>
<symbol id="i-folder" viewBox="0 0 24 24"><path d="M3 7.5A2.5 2.5 0 015.5 5H9l2 2.2h7.5A2.5 2.5 0 0121 9.7v7.8a2.5 2.5 0 01-2.5 2.5h-13A2.5 2.5 0 013 17.5z"/></symbol>
<symbol id="i-archive" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="5" rx="1.8"/><path d="M5 9v9a2 2 0 002 2h10a2 2 0 002-2V9M10 13h4"/></symbol>
<symbol id="i-download" viewBox="0 0 24 24"><path d="M12 4v11m0 0l-4-4m4 4l4-4M5 19.5h14"/></symbol>
<symbol id="i-trash" viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M9 7V4h6v3"/></symbol>
<symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
<symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></symbol>
<symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2.8"/><path d="M5 15V6.5A2.5 2.5 0 017.5 4H16"/></symbol>
<symbol id="i-send" viewBox="0 0 24 24"><path d="M21 3L10.5 13.5M21 3l-6.5 18-4-7.5L3 9.5z"/></symbol>
<symbol id="i-clip" viewBox="0 0 24 24"><rect x="6" y="5" width="12" height="16" rx="2.8"/><path d="M9 5a3 3 0 016 0"/></symbol>
<symbol id="i-power" viewBox="0 0 24 24"><path d="M12 3v8M7 6.5a7 7 0 1010 0"/></symbol>
<symbol id="i-retry" viewBox="0 0 24 24"><path d="M20 12a8 8 0 10-2.4 5.7M20 5v5h-5"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></symbol>
<symbol id="i-chev" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></symbol>
<symbol id="i-home" viewBox="0 0 24 24"><path d="M4 11l8-7 8 7v8.5a1.5 1.5 0 01-1.5 1.5h-13A1.5 1.5 0 014 19.5zM10 21v-6h4v6"/></symbol>
<symbol id="i-sel" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.3l2.5 2.5 4.5-5"/></symbol>
</defs></svg>

<main>
<header>
  <div class="brand"><div class="logo glass"><svg class="ic"><use href="#i-swap"/></svg></div>
    <div><h1>Phone2PC</h1><div class="mut">Private · stays on your Wi-Fi</div></div></div>
  <button id="connectBtn" class="glassbtn hide"><svg class="ic"><use href="#i-phone"/></svg>Connect phone</button>
</header>

<div id="login" class="glass card hide">
  <h2>Enter PIN</h2><p class="mut">Shown on the PC in the Connect panel.</p>
  <input id="pin" type="password" inputmode="numeric" autocomplete="off" placeholder="••••" style="margin-top:10px">
  <div class="row c" style="margin-top:14px"><button id="go">Connect</button></div>
  <p id="lerr" class="mut" style="color:var(--err);text-align:center"></p>
</div>

<div id="app" class="hide">
<div class="seg glass" id="seg"><i class="thumb"></i>
  <button data-tab="files" class="on">Files</button><button data-tab="text">Text</button></div>

<section id="t-files">
  <div class="glass card">
    <div id="drop" class="drop">
      <div class="row c">
        <label class="btn"><svg class="ic"><use href="#i-photo"/></svg>Photos &amp; videos<input id="fPhoto" type="file" accept="image/*,video/*" multiple hidden></label>
        <label class="btn glassbtn"><svg class="ic"><use href="#i-file"/></svg>Files<input id="fAny" type="file" multiple hidden></label>
        <label class="btn glassbtn hide" id="dirBtn"><svg class="ic"><use href="#i-folder"/></svg>Folder<input id="fDir" type="file" webkitdirectory multiple hidden></label>
      </div>
      <p class="mut" style="margin:12px 0 0"><span id="dd" class="hide">Drop files or whole folders here · </span>Goes into the folder you have open below</p>
    </div>
    <div class="row" style="margin-top:12px">
      <span class="mut">At once</span><select id="conc"><option>1</option><option>2</option><option>3</option><option>4</option><option>6</option></select>
      <span id="qs" class="mut"></span>
      <span class="row sp"><button id="retry" class="glassbtn sm"><svg class="ic"><use href="#i-retry"/></svg>Retry</button><button id="clr" class="glassbtn sm">Clear</button></span>
    </div>
    <p id="hint" class="mut hide">Keep this page open while uploading. Tip: start the server with --https so the screen can stay awake.</p>
    <div id="queue"></div>
  </div>

  <div class="glass card">
    <div class="row" style="justify-content:space-between;margin-bottom:6px">
      <div id="crumbs"></div>
      <span class="row"><button id="mk" class="glassbtn sm"><svg class="ic"><use href="#i-plus"/></svg>Folder</button>
      <button id="all" class="glassbtn sm"><svg class="ic"><use href="#i-sel"/></svg>All</button></span>
    </div>
    <div id="lib"></div>
  </div>
</section>

<section id="t-text" class="hide">
  <div class="glass card">
    <textarea id="tx" placeholder="Type or paste text here, then send it to your other device…"></textarea>
    <div class="row" style="margin-top:12px"><button id="tsend"><svg class="ic"><use href="#i-send"/></svg>Send</button>
      <button id="tpaste" class="glassbtn"><svg class="ic"><use href="#i-clip"/></svg>Paste</button>
      <button id="tclear" class="glassbtn danger sp"><svg class="ic"><use href="#i-trash"/></svg>Clear all</button></div>
  </div>
  <div id="tl"></div>
</section>
</div>
</main>

<div id="dock" class="dock glass"><b id="sn"></b>
  <a id="sdl" class="btn sm" download></a>
  <button id="sdel" class="glassbtn danger sm"><svg class="ic"><use href="#i-trash"/></svg>Delete</button>
  <button id="sclr" class="glassbtn sm iconbtn" aria-label="Clear selection"><svg class="ic"><use href="#i-x"/></svg></button></div>

<div id="sheet" class="scrim"><div class="sheet glass">
  <div class="row" style="justify-content:space-between"><h2>Connect your phone</h2>
    <button id="sclose" class="glassbtn iconbtn" aria-label="Close"><svg class="ic"><use href="#i-x"/></svg></button></div>
  <p class="mut">Join the same Wi-Fi, then scan the code or open the address.</p>
  <div id="qr" class="qr"></div>
  <div id="url" class="url"></div>
  <div class="row c"><button id="curl" class="glassbtn sm"><svg class="ic"><use href="#i-copy"/></svg>Copy address</button></div>
  <p class="mut" style="margin-top:16px;text-align:center">PIN</p>
  <div id="pinv" class="pin"></div>
  <div class="row c"><button id="npin" class="glassbtn sm"><svg class="ic"><use href="#i-retry"/></svg>New PIN</button></div>
  <p class="mut" style="margin-top:16px">Shared folder</p>
  <div id="dirv" class="pathbox"></div>
  <div class="row"><button id="ofold" class="glassbtn sm"><svg class="ic"><use href="#i-folder"/></svg>Open folder</button>
    <button id="quit" class="glassbtn danger sm sp"><svg class="ic"><use href="#i-power"/></svg>Quit app</button></div>
</div></div>

<div id="bye" class="scrim"><div class="sheet glass" style="text-align:center"><svg class="ic big"><use href="#i-power"/></svg>
  <h2>Phone2PC has stopped</h2><p class="mut">You can close this window. Start it again any time.</p></div></div>
<div id="toast" class="glass"></div>

<script>
const $=s=>document.querySelector(s),esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ic=(n,c='')=>`<svg class="ic ${c}"><use href="#i-${n}"/></svg>`;
const fmt=b=>b>=1e9?(b/1e9).toFixed(2)+' GB':b>=1e6?(b/1e6).toFixed(1)+' MB':b>=1e3?Math.round(b/1e3)+' KB':b+' B';
const sleep=ms=>new Promise(r=>setTimeout(r,ms)),CH=8*1024*1024;
let pin=localStorage.getItem('p2p_pin')||'',cwd='',sel=new Set(),entries=[],texts=[],queue=[],active=0,seq=0,tab='files',lastT='',isLocal=false,info=null,
    conc=+(localStorage.getItem('p2p_conc')||3);
const dev=/Android|iPhone|iPad|Mobi/i.test(navigator.userAgent)?'Phone':'PC';
const pq=()=>'pin='+encodeURIComponent(pin),ep=p=>p.split('/').map(encodeURIComponent).join('/'),sub=n=>(cwd?cwd+'/':'')+n;
const when=t=>new Date(t*1000).toLocaleString([],{dateStyle:'short',timeStyle:'short'});
const dshort=t=>new Date(t*1000).toLocaleDateString([],{day:'numeric',month:'short',year:'2-digit'});
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('on');clearTimeout(toast.t);toast.t=setTimeout(()=>t.classList.remove('on'),1700);}
async function j(u,o={}){const r=await fetch(u,{...o,headers:{'X-Pin':pin,'X-P2P':'1',...(o.headers||{})}});if(r.status===401)throw 401;
  const b=await r.json().catch(()=>({}));if(!r.ok)throw Object.assign(new Error(b.error||r.status),{status:r.status,body:b});return b;}
const post=(u,b={})=>j(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
function h53(s){let a=0xdeadbeef,b=0x41c6ce57;for(let i=0;i<s.length;i++){const c=s.charCodeAt(i);a=Math.imul(a^c,2654435761);b=Math.imul(b^c,1597334677);}
  a=Math.imul(a^(a>>>16),2246822507)^Math.imul(b^(b>>>13),3266489909);b=Math.imul(b^(b>>>16),2246822507)^Math.imul(a^(a>>>13),3266489909);
  return(b>>>0).toString(16).padStart(8,'0')+(a>>>0).toString(16).padStart(8,'0');}

/* ---------- start / login ---------- */
async function start(){try{const c=await(await fetch('/api/config')).json();isLocal=!!c.local;$('#connectBtn').classList.toggle('hide',!isLocal);
  if(c.pin)await j('/api/list?path=');enter();}catch(e){$('#login').classList.remove('hide');$('#app').classList.add('hide');}}
function enter(){$('#login').classList.add('hide');$('#app').classList.remove('hide');refresh();}
$('#go').onclick=async()=>{pin=$('#pin').value.trim();try{await j('/api/list?path=');localStorage.setItem('p2p_pin',pin);$('#lerr').textContent='';enter();}catch(e){$('#lerr').textContent='Wrong PIN';}};
$('#pin').addEventListener('keydown',e=>{if(e.key==='Enter')$('#go').click();});

/* ---------- tabs ---------- */
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;
  document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('on',x===b));$('#seg').classList.toggle('t1',tab==='text');
  $('#t-files').classList.toggle('hide',tab!=='files');$('#t-text').classList.toggle('hide',tab!=='text');tab==='files'?refresh():loadTexts();});

/* ---------- upload engine: parallel files, chunked + resumable ---------- */
function addFiles(list){for(const {file,path} of list){const full=sub(path);
  const it={id:++seq,file,path:full,sent:0,state:'wait',uid:h53(full+'|'+file.size+'|'+file.lastModified),err:''};queue.push(it);mkEl(it);draw(it);}
  $('#hint').classList.toggle('hide',window.isSecureContext||!queue.length);pump();}
function mkEl(it){const el=document.createElement('div');el.className='item';
  el.innerHTML='<div class="nm"><span class="n"></span><span class="st"></span><button class="x" aria-label="Cancel">'+ic('x')+'</button></div><div class="bar"><i></i></div>';
  el.querySelector('.n').textContent=it.path+' ('+fmt(it.file.size)+')';el.querySelector('.x').onclick=()=>cancel(it);it.el=el;$('#queue').prepend(el);}
function draw(it){const el=it.el;if(!el)return;const p=it.file.size?Math.min(100,Math.round(it.sent/it.file.size*100)):100;
  el.className='item '+(it.state==='done'?'done':(it.state==='fail'||it.state==='cancel')?'fail':'');
  el.querySelector('i').style.width=(it.state==='done'?100:p)+'%';
  el.querySelector('.st').textContent={wait:'Waiting',up:p+'%',retry:'Retrying…',done:'Saved',fail:it.err||'Failed',cancel:'Cancelled'}[it.state];}
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
  x.open('PUT','/api/upload/chunk?uid='+it.uid+'&offset='+off);x.setRequestHeader('X-Pin',pin);x.setRequestHeader('X-P2P','1');
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
const kind=e=>e.dir?'folder':/^video/.test(e.type)?'video':/^image/.test(e.type)?'image':/\.(zip|7z|rar|gz|tar)$/i.test(e.name)?'zip':'file';
const KI={folder:'folder',video:'video',image:'image',zip:'archive',file:'file'};
function drawLib(){let acc='';
  $('#crumbs').innerHTML='<a data-go="">'+ic('home')+'</a>'+cwd.split('/').filter(Boolean).map(s=>{acc+=(acc?'/':'')+s;return ic('chev')+`<a data-go="${esc(acc)}">${esc(s)}</a>`;}).join('');
  $('#lib').innerHTML=entries.length?entries.map(e=>{const r=sub(e.name),k=kind(e),
    th=(k==='image'&&e.size<6e6)?`<img loading="lazy" src="/files/${ep(r)}?${pq()}">`:ic(KI[k]);
    const nm=e.dir?`<a data-go="${esc(r)}">${esc(e.name)}</a>`:`<a target="_blank" href="/files/${ep(r)}?${pq()}">${esc(e.name)}</a>`;
    const dl=e.dir?`/zip?p=${encodeURIComponent(r)}&${pq()}`:`/dl/${ep(r)}?${pq()}`;
    return`<div class="file"><input type="checkbox" data-sel="${esc(r)}" ${sel.has(r)?'checked':''} aria-label="Select">
      <div class="th k-${k}">${th}</div><div class="fi">${nm}<div class="mut">${e.dir?'Folder':fmt(e.size)} · ${dshort(e.mtime)}</div></div>
      ${/\.zip$/i.test(e.name)?`<button class="glassbtn sm" data-unzip="${esc(r)}">${ic('archive')}<span class="lbl">Unzip</span></button>`:''}
      <a class="btn sm" href="${dl}" download>${ic('download')}${e.dir?'ZIP':''}</a></div>`;}).join('')
    :`<div class="empty">${ic('folder','big')}<p><b>This folder is empty</b></p><p class="mut">Upload from either device and it appears here.</p></div>`;
  drawSel();}
function drawSel(){const n=sel.size,d=$('#dock');d.classList.toggle('show',n>0);if(!n)return;$('#sn').textContent=n+' selected';
  const a=[...sel],one=a.length===1&&entries.find(e=>sub(e.name)===a[0]&&!e.dir);
  $('#sdl').href=one?`/dl/${ep(a[0])}?${pq()}`:`/zip?${a.map(p=>'p='+encodeURIComponent(p)).join('&')}&${pq()}`;
  $('#sdl').innerHTML=ic('download')+(one?'Download':'ZIP');}
document.addEventListener('click',async e=>{const g=e.target.closest('[data-go]');if(g){e.preventDefault();cwd=g.dataset.go;sel.clear();refresh();return;}
  const u=e.target.closest('[data-unzip]');if(u){u.disabled=true;toast('Extracting…');try{await post('/api/extract',{path:u.dataset.unzip});toast('Extracted');}catch(x){toast('Extract failed');}refresh();}});
document.addEventListener('change',e=>{const s=e.target.dataset&&e.target.dataset.sel;if(s){e.target.checked?sel.add(s):sel.delete(s);drawSel();}});
$('#all').onclick=()=>{if(sel.size===entries.length)sel.clear();else entries.forEach(e=>sel.add(sub(e.name)));drawLib();};
$('#sclr').onclick=()=>{sel.clear();drawLib();};
$('#sdel').onclick=async()=>{if(!confirm(`Delete ${sel.size} item(s) from the PC? This cannot be undone.`))return;await post('/api/delete',{paths:[...sel]});sel.clear();refresh();};
$('#mk').onclick=async()=>{const n=prompt('New folder name');if(!n)return;try{await post('/api/mkdir',{path:sub(n)});}catch(e){toast('Could not create folder');}refresh();};

/* ---------- shared text ---------- */
async function loadTexts(){try{const t=await j('/api/texts'),s=JSON.stringify(t);if(s===lastT)return;lastT=s;texts=t;
  $('#tl').innerHTML=t.length?t.map(x=>`<div class="snip glass"><div class="dev">${ic(x.device==='Phone'?'phone':'laptop')}${esc(x.device)} · ${when(x.ts)}</div><pre>${esc(x.text)}</pre>
    <div class="row"><button class="sm" data-copy="${x.id}">${ic('copy')}Copy</button><button class="glassbtn sm danger" data-tdel="${x.id}">${ic('trash')}Delete</button></div></div>`).join('')
    :`<div class="glass card empty">${ic('clip','big')}<p><b>Nothing shared yet</b></p><p class="mut">Send text from either device and copy it on the other.</p></div>`;}catch(e){}}
async function copy(t){try{await navigator.clipboard.writeText(t);}catch(e){const a=document.createElement('textarea');a.value=t;a.style.cssText='position:fixed;opacity:0';
  document.body.append(a);a.focus();a.select();try{document.execCommand('copy')}catch(_){}a.remove();}toast('Copied');}
document.addEventListener('click',async e=>{const c=e.target.closest('[data-copy]');if(c){const x=texts.find(t=>t.id===c.dataset.copy);x&&copy(x.text);}
  const d=e.target.closest('[data-tdel]');if(d){await post('/api/texts/delete',{id:d.dataset.tdel});lastT='';loadTexts();}});
$('#tsend').onclick=async()=>{const v=$('#tx').value;if(!v.trim())return;await post('/api/texts',{text:v,device:dev});$('#tx').value='';lastT='';loadTexts();toast('Sent');};
$('#tpaste').onclick=async()=>{try{$('#tx').value=await navigator.clipboard.readText();}catch(e){toast('Long-press the box and choose Paste');$('#tx').focus();}};
$('#tclear').onclick=async()=>{if(!confirm('Delete all shared text?'))return;await post('/api/texts/delete',{all:true});lastT='';loadTexts();};

/* ---------- connect sheet (PC only) ---------- */
function showInfo(){$('#qr').innerHTML=info.qr;$('#url').textContent=info.url;$('#dirv').textContent=info.dir;
  $('#pinv').innerHTML=info.pin?info.pin.split('').map(d=>`<b>${d}</b>`).join(''):'<span class="mut">PIN is off</span>';}
$('#connectBtn').onclick=async()=>{try{info=await j('/api/info');showInfo();$('#sheet').classList.add('show');}catch(e){toast('Unavailable');}};
$('#sclose').onclick=()=>$('#sheet').classList.remove('show');
$('#sheet').addEventListener('click',e=>{if(e.target.id==='sheet')$('#sheet').classList.remove('show');});
$('#curl').onclick=()=>info&&copy(info.url);
$('#npin').onclick=async()=>{const r=await post('/api/pin/new');info.pin=r.pin;showInfo();toast('New PIN set');};
$('#ofold').onclick=()=>post('/api/open-folder').catch(()=>toast('Could not open folder'));
$('#quit').onclick=async()=>{if(!confirm('Quit Phone2PC? Phone transfers will stop.'))return;try{await post('/api/quit');}catch(e){}
  $('#sheet').classList.remove('show');$('#bye').classList.add('show');setTimeout(()=>{try{window.close()}catch(e){}},600);};

setInterval(()=>{if(document.hidden||$('#app').classList.contains('hide'))return;tab==='text'?loadTexts():(active||refresh());},3000);
/* ---------- cursor spotlight ---------- */
(()=>{const root=document.documentElement;let raf=0,px=-9999,py=-9999,on=false;
  function upd(){raf=0;if(on){root.style.setProperty('--mx',px+'px');root.style.setProperty('--my',py+'px');}
    for(const g of document.querySelectorAll('.glass')){const r=g.getBoundingClientRect(),
      d=Math.hypot(Math.max(r.left-px,0,px-r.right),Math.max(r.top-py,0,py-r.bottom));
      g.style.setProperty('--lx',(px-r.left)+'px');g.style.setProperty('--ly',(py-r.top)+'px');g.style.setProperty('--sa',on?Math.max(0,1-d/220).toFixed(2):'0');}}
  const mv=e=>{px=e.clientX;py=e.clientY;on=true;if(!raf)raf=requestAnimationFrame(upd);};
  const off=()=>{on=false;px=py=-9999;if(!raf)raf=requestAnimationFrame(upd);};
  addEventListener('pointermove',mv,{passive:true});addEventListener('pointerdown',mv,{passive:true});
  addEventListener('pointerup',e=>{if(e.pointerType==='touch')setTimeout(off,700);});
  document.documentElement.addEventListener('mouseleave',off);addEventListener('blur',off);
  addEventListener('scroll',()=>{if(on&&!raf)raf=requestAnimationFrame(upd);},{passive:true});})();

start();
</script></body></html>"""


# ------------------------------------------------------------------ QR code (byte mode, ECC M, versions 1-10)
_ECC_PER_BLOCK = [10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
_NUM_BLOCKS = [1, 1, 1, 2, 2, 4, 4, 4, 5, 5]


def _gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    r, root = [0] * (degree - 1) + [1], 1
    for _ in range(degree):
        for j in range(degree):
            r[j] = _gf_mul(r[j], root)
            if j + 1 < degree:
                r[j] ^= r[j + 1]
        root = _gf_mul(root, 2)
    return r


def _rs_remainder(data, div):
    r = [0] * len(div)
    for b in data:
        f = b ^ r.pop(0)
        r.append(0)
        for i, c in enumerate(div):
            r[i] ^= _gf_mul(c, f)
    return r


def _raw_modules(v):
    r = (16 * v + 128) * v + 64
    if v >= 2:
        na = v // 7 + 2
        r -= (25 * na - 10) * na - 55
        if v >= 7:
            r -= 36
    return r


def qr_matrix(text):
    data = text.encode("utf-8")
    for ver in range(1, 11):
        nb, ecc = _NUM_BLOCKS[ver - 1], _ECC_PER_BLOCK[ver - 1]
        raw = _raw_modules(ver) // 8
        cap = raw - ecc * nb
        ccbits = 8 if ver <= 9 else 16
        if 4 + ccbits + 8 * len(data) <= cap * 8:
            break
    else:
        raise ValueError("text too long for QR")
    bits = []

    def put(val, n):
        bits.extend((val >> i) & 1 for i in range(n - 1, -1, -1))

    put(0b0100, 4)
    put(len(data), ccbits)
    for b in data:
        put(b, 8)
    put(0, min(4, cap * 8 - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    cw = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(cw) < cap:
        cw.append(pad)
        pad ^= 0xEC ^ 0x11
    # split into blocks, add error correction, interleave
    div = _rs_divisor(ecc)
    nshort, slen = nb - raw % nb, raw // nb
    blocks, k = [], 0
    for i in range(nb):
        d = cw[k:k + slen - ecc + (0 if i < nshort else 1)]
        k += len(d)
        e = _rs_remainder(d, div)
        if i < nshort:
            d = d + [0]
        blocks.append(d + e)
    final = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != slen - ecc or j >= nshort:
                final.append(blk[i])
    # draw function patterns
    size = ver * 4 + 17
    mod = [[False] * size for _ in range(size)]
    fn = [[False] * size for _ in range(size)]

    def setf(x, y, d):
        mod[y][x] = bool(d)
        fn[y][x] = True

    for i in range(size):
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    setf(x, y, max(abs(dx), abs(dy)) not in (2, 4))
    if ver > 1:
        na = ver // 7 + 2
        step = (ver * 8 + na * 3 + 5) // (na * 4 - 4) * 2
        pos = list(range(size - 7, 6, -step)) + [6]
        pos.reverse()
        for i, cx in enumerate(pos):
            for j, cy in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == na - 1) or (i == na - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        setf(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)

    def draw_format(mask):
        d = mask  # ECC level M has format bits 00
        rem = d
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        fb = ((d << 10) | rem) ^ 0x5412
        g = lambda i: (fb >> i) & 1
        for i in range(6):
            setf(8, i, g(i))
        setf(8, 7, g(6))
        setf(8, 8, g(7))
        setf(7, 8, g(8))
        for i in range(9, 15):
            setf(14 - i, 8, g(i))
        for i in range(8):
            setf(size - 1 - i, 8, g(i))
        for i in range(8, 15):
            setf(8, size - 15 + i, g(i))
        setf(8, size - 8, True)

    draw_format(0)
    if ver >= 7:
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        vb = (ver << 12) | rem
        for i in range(18):
            a, b = size - 11 + i % 3, i // 3
            setf(a, b, (vb >> i) & 1)
            setf(b, a, (vb >> i) & 1)
    # place data bits in the zig-zag order
    i = 0
    for right in range(size - 1, 0, -2):
        if right <= 6:
            right -= 1
        for vert in range(size):
            for j in range(2):
                x = right - j
                y = size - 1 - vert if ((right + 1) & 2) == 0 else vert
                if not fn[y][x] and i < len(final) * 8:
                    mod[y][x] = bool((final[i >> 3] >> (7 - (i & 7))) & 1)
                    i += 1

    masks = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
             lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
             lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
             lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]

    def apply(m):
        f = masks[m]
        for y in range(size):
            for x in range(size):
                if not fn[y][x] and f(x, y):
                    mod[y][x] = not mod[y][x]

    def penalty():
        p = 0
        for grid in (mod, [list(c) for c in zip(*mod)]):
            for row in grid:
                run = 1
                for k2 in range(1, size):
                    if row[k2] == row[k2 - 1]:
                        run += 1
                    else:
                        if run >= 5:
                            p += run - 2
                        run = 1
                if run >= 5:
                    p += run - 2
        for y in range(size - 1):
            for x in range(size - 1):
                if mod[y][x] == mod[y][x + 1] == mod[y + 1][x] == mod[y + 1][x + 1]:
                    p += 3
        dark, total = sum(map(sum, mod)), size * size
        return p + ((abs(dark * 20 - total * 10) + total - 1) // total - 1) * 10

    best, bestp = 0, None
    for m in range(8):
        apply(m)
        draw_format(m)
        pen = penalty()
        apply(m)
        if bestp is None or pen < bestp:
            best, bestp = m, pen
    apply(best)
    draw_format(best)
    return mod


def qr_svg(text):
    m = qr_matrix(text)
    n, q, parts = len(m), 4, []
    for y, row in enumerate(m):
        x = 0
        while x < n:
            if row[x]:
                s = x
                while x < n and row[x]:
                    x += 1
                parts.append(f"M{s + q},{y + q}h{x - s}v1h-{x - s}z")
            else:
                x += 1
    d = "".join(parts)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n + 2 * q} {n + 2 * q}" shape-rendering="crispEdges">'
            f'<rect width="100%" height="100%" fill="#fff"/><path d="{d}" fill="#000"/></svg>')


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


def load_cfg():
    try:
        with open(CFG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except OSError:
        pass


def clean(part):
    return re.sub(r'[<>:"|?*\x00-\x1f\\]', "_", part).strip().rstrip(" .")


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


def open_folder(path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


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

    def deny(self, code, msg):
        self.close_connection = True
        self.json_out({"error": msg}, code, {"Connection": "close"})

    def is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def host_ok(self):
        """Blocks DNS-rebinding: only IP literals, localhost, *.local or this machine's name."""
        h = (self.headers.get("Host") or "").strip().lower()
        host = h[1:h.index("]")] if h.startswith("[") and "]" in h else (h.rsplit(":", 1)[0] if ":" in h else h)
        return bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", host)) or host in ("localhost", "::1") \
            or host.endswith(".local") or host == socket.gethostname().lower()

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
        global PIN
        if not self.host_ok():
            return self.deny(421, "bad host")
        u = urlparse(self.path)
        qs, p, m = parse_qs(u.query), u.path, self.command
        q1 = lambda k, d="": (qs.get(k) or [d])[0]
        if m == "GET" and p == "/":
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if m == "GET" and p == "/api/config":
            return self.json_out({"app": "phone2pc", "pin": bool(PIN) and not self.is_local(), "local": self.is_local()})
        if m in ("POST", "PUT") and self.headers.get("X-P2P") != "1":
            return self.deny(403, "missing X-P2P header")  # blocks cross-site form posts
        if not self.authed(qs):
            return self.deny(401, "PIN required")
        if p in ("/api/info", "/api/open-folder", "/api/quit", "/api/pin/new") and not self.is_local():
            return self.deny(403, "PC only")
        body = self.body_json() if m == "POST" else None

        if m == "GET":
            if p == "/api/list":
                d = abspath(rel_clean(q1("path")))
                if not os.path.isdir(d):
                    return self.json_out({"error": "no such folder"}, 404)
                return self.json_out(list_dir(d))
            if p == "/api/info":
                url = f"{SCHEME}://{lan_ip()}:{PORT}"
                return self.json_out({"url": url, "pin": PIN or "", "dir": ROOT, "qr": qr_svg(url)})
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
            if p == "/api/open-folder":
                open_folder(ROOT)
                return self.json_out({"ok": True})
            if p == "/api/pin/new":
                PIN = f"{random.randint(0, 9999):04d}"
                cfg = load_cfg()
                cfg["pin"] = PIN
                save_cfg(cfg)
                return self.json_out({"pin": PIN})
            if p == "/api/quit":
                self.json_out({"ok": True})
                threading.Thread(target=SRV.shutdown, daemon=True).start()
                return
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
        print(f"  + {to_rel(dest)}  ({size / 1e6:.1f} MB)")
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


# ------------------------------------------------------------------ app launch
def make_cert(ip):
    cert, key = os.path.join(META, f"cert-{ip}.pem"), os.path.join(META, f"key-{ip}.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
                        "-days", "825", "-subj", "/CN=phone2pc", "-addext",
                        f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return cert, key


def probe(port):
    """Is a Phone2PC already running on this port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=0.6) as r:
            return json.load(r).get("app") == "phone2pc"
    except Exception:
        return False


def open_app_window(url):
    """Open as a chrome-less app window when Chrome/Edge/Brave/Chromium exists, else the default browser."""
    cands = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if base:
                cands += [os.path.join(base, r"Google\Chrome\Application\chrome.exe"),
                          os.path.join(base, r"Microsoft\Edge\Application\msedge.exe"),
                          os.path.join(base, r"BraveSoftware\Brave-Browser\Application\brave.exe")]
    elif sys.platform == "darwin":
        cands += [f"/Applications/{a}.app/Contents/MacOS/{a}"
                  for a in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium")]
    else:
        cands += [shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium",
                                            "chromium-browser", "microsoft-edge", "brave-browser")]
    for c in cands:
        if c and os.path.exists(c):
            try:
                subprocess.Popen([c, f"--app={url}", "--window-size=1100,820", "--allow-insecure-localhost"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                pass
    webbrowser.open(url)


def main():
    global ROOT, META, TFILE, PIN, SRV, PORT, SCHEME
    if sys.stdout is None:  # launched with pythonw / .pyw
        sys.stdout = sys.stderr = open(os.devnull, "w")
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Phone2PC - share files and text between phone and PC")
    ap.add_argument("--dir")
    ap.add_argument("--port", type=int)
    ap.add_argument("--pin")
    ap.add_argument("--no-pin", action="store_true")
    ap.add_argument("--https", action="store_true")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()

    cfg = load_cfg()
    ROOT = os.path.abspath(os.path.expanduser(a.dir or cfg.get("dir") or os.path.join("~", "Phone2PC")))
    base_port = a.port or cfg.get("port") or 8000
    if a.no_pin:
        PIN = None
    else:
        PIN = a.pin or cfg.get("pin") or f"{random.randint(0, 9999):04d}"
        cfg["pin"] = PIN
    cfg.update({"dir": ROOT, "port": base_port})
    save_cfg(cfg)

    if probe(base_port):  # already running: just bring up the window
        print(f"Phone2PC is already running on port {base_port}.")
        if not a.no_open:
            open_app_window(f"http://localhost:{base_port}")
        return

    META = os.path.join(ROOT, RESERVED)
    TFILE = os.path.join(META, "texts.json")
    os.makedirs(os.path.join(META, "partial"), exist_ok=True)

    srv = None
    for port in range(base_port, base_port + 20):
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
            PORT = port
            break
        except OSError:
            continue
    if srv is None:
        print("Could not find a free port.")
        sys.exit(1)
    SRV = srv

    ip = lan_ip()
    if a.https:
        try:
            cert, key = make_cert(ip)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            srv.socket = ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
            SCHEME = "https"
        except (FileNotFoundError, subprocess.CalledProcessError):
            print("  ! HTTPS needs `openssl` on PATH - continuing with plain HTTP.")

    print("\n  Phone2PC is running")
    print(f"  Shared folder : {ROOT}")
    print(f"  This PC       : http://localhost:{PORT}   (no PIN needed)" if SCHEME == "http"
          else f"  This PC       : https://localhost:{PORT}")
    print(f"  Phone         : {SCHEME}://{ip}:{PORT}   PIN {PIN or '(off)'}")
    print("  Quit from the app window, or press Ctrl+C here.\n")

    if not a.no_open:
        # the PC window always uses plain localhost HTTP-or-HTTPS matching the server
        threading.Timer(0.4, open_app_window, args=(f"{SCHEME}://localhost:{PORT}",)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    print("\n  Phone2PC stopped.")
    time.sleep(0.3)
    os._exit(0)


if __name__ == "__main__":
    main()
