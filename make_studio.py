"""
make_studio.py  --  v0.1.0
==========================================================================
Generates dream-team-studio.html -- a RECORDING build of the Dream Team
game -- from the live index.html.

  python make_studio.py                       # index.html -> dream-team-studio.html
  python make_studio.py path/to/index.html out.html

WHY GENERATED AND NOT FORKED
  A hand-edited copy of an 820KB game diverges the first time the real one
  is patched, and the promo build then shows behaviour that no longer
  exists. This reads index.html and injects the studio layer, so
  regenerating after any change to the game is one command. The game file
  itself is never modified -- it is opened read-only.

WHAT THE STUDIO LAYER ADDS  (all of it inert until ?studio=1)
  FRAMING     1920x1080 / 1080x1920 / 1080x1080 presets. The app is scaled
              and centred on black at exactly those pixels, so a screen
              capture has clean edges and no letterbox guesswork.
  CHROME      one toggle hides the nav, footer, tracker and reset link --
              everything that is furniture rather than the game.
  SEED        ?seed=12345 makes the pool reproducible. dtStart uses
              Math.random, so without this a fluffed take cannot be
              re-shot with the same thirty cards.
  PACING      a speed dial on the reveal holds. The 650ms card reveal is
              right for playing and too fast to read on video.
  RECORD      getDisplayMedia + MediaRecorder, straight to a .webm
              download. No extension, no capture software.

  Nothing here touches the game's logic, its scoring or its tracker. The
  studio layer only reads and re-times.

DEPLOY
  Drop dream-team-studio.html beside index.html in aderoa/boxscorelab and
  open it on GitHub Pages:
      aderoa.github.io/boxscorelab/dream-team-studio.html?studio=1&seed=7
  It fetches data.bin relatively, from the same folder, so it needs no
  Worker route and picks up no injected nav. Do NOT put it behind
  /dream-team-game -- that route serves index.html and would ignore it.
==========================================================================
"""

import io
import os
import re
import sys

VERSION = "v0.1.0"
DEFAULT_IN = "index.html"
DEFAULT_OUT = "dream-team-studio.html"


STUDIO_CSS = """
/* ===== STUDIO LAYER -- inert without ?studio=1 ===== */
body.studio{background:#000;overflow:hidden;height:100vh}
body.studio #hm-nav-root,body.studio .mode-tabs,body.studio .app-footer,
body.studio.hide-chrome .dt-stats,body.studio.hide-chrome .dt-reset,
body.studio.hide-chrome .dt-lastten{display:none!important}
/* The stage is the exact output frame. Scaling the app instead of resizing
   the window means the capture is pixel-exact whatever the display is. */
#stage{position:fixed;left:50%;top:50%;transform-origin:50% 50%;
  background:linear-gradient(145deg,#1a1a3e 0%,#0a0a1a 50%,#ffffff 100%);
  overflow:hidden;box-shadow:0 0 0 1px rgba(255,255,255,.14)}
body.studio #app{height:100%;overflow-y:auto;overflow-x:hidden}
body.studio.locked #app{overflow:hidden}
#recbar{position:fixed;left:0;right:0;bottom:0;z-index:99999;display:flex;
  gap:8px;align-items:center;flex-wrap:wrap;padding:8px 12px;
  background:rgba(8,8,16,.92);border-top:1px solid rgba(255,255,255,.14);
  font:12px/1.4 'JetBrains Mono',ui-monospace,monospace;color:#dfe6f2}
#recbar.away{transform:translateY(110%)}
#recbar button,#recbar select,#recbar input{font:inherit;color:#dfe6f2;
  background:#171e2b;border:1px solid #2b3546;border-radius:6px;padding:5px 9px;
  cursor:pointer;outline:none}
#recbar input{width:86px;cursor:text}
#recbar button.on{background:#e0a13a;border-color:#e0a13a;color:#1a1206;font-weight:700}
#recbar button.rec{background:#c0392b;border-color:#c0392b;color:#fff;font-weight:700}
#recbar .sp{flex:1}
#recbar .lbl{opacity:.6;letter-spacing:.08em;text-transform:uppercase;font-size:10px}
#rectime{font-variant-numeric:tabular-nums;letter-spacing:.05em}
#recdot{width:9px;height:9px;border-radius:50%;background:#c0392b;display:none}
#recdot.on{display:inline-block;animation:recblink 1s steps(2) infinite}
@keyframes recblink{50%{opacity:.15}}
#recnote{position:fixed;left:12px;top:12px;z-index:99999;max-width:30ch;
  padding:8px 10px;border-radius:8px;background:rgba(8,8,16,.9);
  border:1px solid rgba(255,255,255,.14);color:#dfe6f2;
  font:11px/1.45 'JetBrains Mono',ui-monospace,monospace;display:none}
"""


STUDIO_JS = r"""
/* ===== STUDIO LAYER =====================================================
   Recording harness. Reads the game and re-times it; changes no rule of
   it. Everything below is a no-op unless ?studio=1 is present, so this
   file behaves exactly like index.html when opened without it.
   ====================================================================== */
(function () {
  var Q = new URLSearchParams(location.search);
  if (!Q.has("studio")) return;

  var FRAMES = {
    "1920x1080": [1920, 1080], "1280x720": [1280, 720],
    "1080x1920": [1080, 1920], "1080x1080": [1080, 1080]
  };
  var S = { frame: Q.get("frame") || "1920x1080", chrome: false,
            speed: parseFloat(Q.get("speed") || "1"), rec: null,
            chunks: [], t0: 0, timer: null };

  /* ---- deterministic pool ---------------------------------------------
     dtStart seeds from Math.random, which is right for a real game and
     useless for a re-shoot: a fluffed take cannot be repeated with the
     same thirty cards. With ?seed=N, Math.random is replaced by the
     game's OWN generator (dtRng, a mulberry32) for the duration of
     dtStart only -- so the pool is reproducible without altering a single
     rule, and every later call to Math.random is untouched. */
  var seed = Q.get("seed");
  if (seed && typeof window.dtStart === "function"
           && typeof window.dtRng === "function") {
    var realStart = window.dtStart;
    window.dtStart = function () {
      var realRandom = Math.random;
      var g = window.dtRng((parseInt(seed, 10) >>> 0) || 1);
      Math.random = g;
      try { return realStart.apply(this, arguments); }
      finally { Math.random = realRandom; }
    };
  }

  /* ---- pacing ---------------------------------------------------------
     The card reveal holds 650ms, which reads fine while playing and is
     too fast to follow on video. Scale every timeout the game sets rather
     than hunting each constant: the game uses setTimeout for the reveal
     hold, the leftover reveal and the confetti, and slowing all of them
     together is what a slow-motion take wants. Anything under 40ms is
     left alone -- those are layout ticks, not beats. */
  var realTimeout = window.setTimeout;
  window.setTimeout = function (fn, ms) {
    var a = [].slice.call(arguments, 2);
    var d = (typeof ms === "number" && ms >= 40) ? ms * S.speed : ms;
    return realTimeout.apply(window, [fn, d].concat(a));
  };

  /* ---- stage ---------------------------------------------------------- */
  var stage, app;
  function build() {
    app = document.getElementById("app");
    if (!app) return false;
    stage = document.createElement("div");
    stage.id = "stage";
    app.parentNode.insertBefore(stage, app);
    stage.appendChild(app);
    var ls = document.getElementById("loadScreen");
    if (ls) stage.insertBefore(ls, app);
    document.body.classList.add("studio");
    return true;
  }

  function fit() {
    if (!stage) return;
    var f = FRAMES[S.frame] || FRAMES["1920x1080"];
    stage.style.width = f[0] + "px";
    stage.style.height = f[1] + "px";
    var barH = 46;
    var k = Math.min(window.innerWidth / f[0],
                     (window.innerHeight - barH) / f[1]);
    stage.style.transform = "translate(-50%,-50%) scale(" + k + ")";
    stage.style.marginTop = (-barH / 2) + "px";
    var pct = document.getElementById("recscale");
    if (pct) pct.textContent = Math.round(k * 100) + "%";
  }

  /* ---- recording ------------------------------------------------------
     getDisplayMedia, so the operator picks the tab and the browser draws
     the frames -- no canvas mirror of a DOM game, which would miss the
     CSS animations that are most of what makes it look alive. */
  function pickType() {
    var want = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8',
                'video/webm', 'video/mp4'];
    for (var i = 0; i < want.length; i++)
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(want[i]))
        return want[i];
    return "";
  }

  function note(msg) {
    var n = document.getElementById("recnote");
    n.textContent = msg;
    n.style.display = msg ? "block" : "none";
  }

  function tick() {
    var s = Math.floor((Date.now() - S.t0) / 1000);
    document.getElementById("rectime").textContent =
      String(Math.floor(s / 60)).padStart(2, "0") + ":" +
      String(s % 60).padStart(2, "0");
  }

  async function start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      note("This browser has no getDisplayMedia. Chrome or Edge works.");
      return;
    }
    var stream;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 60 }, audio: false
      });
    } catch (e) { note("Capture cancelled."); return; }
    var type = pickType();
    if (!type) { note("No MediaRecorder codec available."); return; }
    S.chunks = [];
    S.rec = new MediaRecorder(stream, { mimeType: type,
                                        videoBitsPerSecond: 12000000 });
    S.rec.ondataavailable = function (e) {
      if (e.data && e.data.size) S.chunks.push(e.data);
    };
    S.rec.onstop = function () {
      stream.getTracks().forEach(function (t) { t.stop(); });
      var blob = new Blob(S.chunks, { type: type });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "dream-team-" + S.frame + "-" + Date.now() +
                   (type.indexOf("mp4") >= 0 ? ".mp4" : ".webm");
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
      note("Saved " + a.download);
    };
    // If the operator ends the share from the browser's own bar rather
    // than this one, stop cleanly instead of recording a dead track.
    stream.getVideoTracks()[0].addEventListener("ended", function () {
      if (S.rec && S.rec.state === "recording") stop();
    });
    S.rec.start(1000);
    S.t0 = Date.now();
    S.timer = setInterval(tick, 500);
    document.getElementById("recbtn").textContent = "Stop";
    document.getElementById("recbtn").classList.add("rec");
    document.getElementById("recdot").classList.add("on");
    note("Recording. Pick this tab in the share dialog for a clean frame.");
  }

  function stop() {
    if (S.rec && S.rec.state !== "inactive") S.rec.stop();
    S.rec = null;
    clearInterval(S.timer);
    document.getElementById("recbtn").textContent = "Record";
    document.getElementById("recbtn").classList.remove("rec");
    document.getElementById("recdot").classList.remove("on");
  }

  /* ---- toolbar -------------------------------------------------------- */
  function bar() {
    var d = document.createElement("div");
    d.id = "recbar";
    d.innerHTML =
      '<span id="recdot"></span>' +
      '<button id="recbtn">Record</button>' +
      '<span id="rectime">00:00</span>' +
      '<span class="lbl">frame</span><select id="recframe"></select>' +
      '<span id="recscale" class="lbl"></span>' +
      '<span class="lbl">speed</span><select id="recspeed">' +
        '<option value="1">1x</option><option value="1.5">1.5x</option>' +
        '<option value="2">2x</option><option value="3">3x</option>' +
        '<option value="0.75">0.75x</option></select>' +
      '<button id="recchrome">Hide chrome</button>' +
      '<span class="lbl">seed</span><input id="recseed" placeholder="random">' +
      '<button id="recreload">Apply</button>' +
      '<div class="sp"></div>' +
      '<span class="lbl">H hides this bar</span>';
    document.body.appendChild(d);
    var n = document.createElement("div");
    n.id = "recnote";
    document.body.appendChild(n);

    var fs = document.getElementById("recframe");
    Object.keys(FRAMES).forEach(function (k) {
      var o = document.createElement("option");
      o.value = o.textContent = k;
      if (k === S.frame) o.selected = true;
      fs.appendChild(o);
    });
    document.getElementById("recspeed").value = String(S.speed);
    document.getElementById("recseed").value = seed || "";

    document.getElementById("recbtn").onclick = function () {
      if (S.rec) stop(); else start();
    };
    fs.onchange = function () { S.frame = fs.value; fit(); };
    document.getElementById("recspeed").onchange = function (e) {
      S.speed = parseFloat(e.target.value) || 1;
      note("Speed " + S.speed + "x applies to the next reveal.");
    };
    document.getElementById("recchrome").onclick = function () {
      S.chrome = !S.chrome;
      document.body.classList.toggle("hide-chrome", S.chrome);
      this.classList.toggle("on", S.chrome);
    };
    // seed and frame belong in the URL: a re-shoot should be a reload, not
    // a sequence of clicks somebody has to remember.
    document.getElementById("recreload").onclick = function () {
      var q = new URLSearchParams(location.search);
      q.set("studio", "1");
      q.set("frame", S.frame);
      q.set("speed", String(S.speed));
      var v = document.getElementById("recseed").value.trim();
      if (v) q.set("seed", v); else q.delete("seed");
      location.search = q.toString();
    };
    addEventListener("keydown", function (e) {
      if (e.key === "h" || e.key === "H")
        d.classList.toggle("away");
    });
  }

  function go() {
    if (!build()) { realTimeout(go, 60); return; }
    bar();
    fit();
    addEventListener("resize", fit);
    if (Q.get("chrome") === "0")
      document.getElementById("recchrome").click();
  }
  if (document.readyState === "loading")
    addEventListener("DOMContentLoaded", go);
  else go();
})();
"""


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IN
    dst = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    if not os.path.exists(src):
        print(f"not found: {src}")
        print("  point this at the Dream Team index.html")
        return
    if os.path.abspath(src) == os.path.abspath(dst):
        print("refusing to write over the source -- the game must not change")
        return

    html = io.open(src, encoding="utf-8", newline="").read()

    # anchors, asserted: a silent miss would produce a studio file with no
    # studio in it, and that is exactly the sort of thing nobody notices
    # until the recording session
    if "</style>" not in html:
        print("!! no </style> found -- is this the game file?")
        return
    if "</body>" not in html:
        print("!! no </body> found")
        return

    # last </style> so the studio rules win on equal specificity
    i = html.rfind("</style>")
    html = html[:i] + STUDIO_CSS + html[i:]

    stamp = ("\n<!-- dream-team-studio, generated by make_studio.py "
             f"{VERSION} -- do not hand-edit, regenerate -->\n")
    j = html.rfind("</body>")
    html = (html[:j] + stamp + "<script>" + STUDIO_JS + "</script>\n"
            + html[j:])

    title = re.search(r"<title>(.*?)</title>", html, re.S)
    if title:
        html = html.replace(title.group(0),
                            "<title>" + title.group(1).strip()
                            + " \u2014 studio</title>", 1)

    io.open(dst, "w", encoding="utf-8", newline="").write(html)
    print(f"make_studio {VERSION}")
    print(f"  {src}  ({os.path.getsize(src)/1024:.0f} KB)")
    print(f"  -> {dst}  ({os.path.getsize(dst)/1024:.0f} KB)")
    print()
    print("  The source was NOT modified.")
    print("  Deploy beside index.html, then open:")
    print("    dream-team-studio.html?studio=1&seed=7&frame=1920x1080")
    print("  Without ?studio=1 it behaves exactly like the game.")


if __name__ == "__main__":
    main()
