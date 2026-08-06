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
  FRAMING     1920x1080 / 1080x1920 / 1080x1080 / window presets, plus
              REGION CAPTURE: the recorded stream is cropped to the stage
              element, so the output contains the game and nothing else.

              Without the crop, tab capture records the whole VIEWPORT --
              a 1080x1080 stage came out as a 2048x1040 file with the game
              letterboxed in the middle and the toolbar along the bottom.
              CropTarget.fromElement fixes that at the source rather than
              leaving it to be trimmed afterwards.

              The crop keeps the element's RENDERED size, so a stage scaled
              to 72% records at 72%. Use the "window" preset, or a frame
              that fits, to record at 1:1 -- the scale readout in the
              toolbar turns amber below 100% to say so.
  CHROME      one toggle hides the nav, footer, tracker and reset link --
              everything that is furniture rather than the game.
  SEED        ?seed=12345 makes the pool reproducible. dtStart uses
              Math.random, so without this a fluffed take cannot be
              re-shot with the same thirty cards.
  PACING      a speed dial on the reveal holds. The 650ms card reveal is
              right for playing and too fast to read on video.
  RECORD      getDisplayMedia + MediaRecorder, straight to a download.

              DEFAULTS TO MP4 WITH A SILENT AUDIO TRACK, because that is what
              Twitter/X accepts. It rejects WebM outright, and it rejects most
              MP4s that carry no audio track at all -- a screen capture has
              none, so one is generated: a Web Audio oscillator at zero gain,
              which is a real, valid, inaudible track.

              Frame sizes are forced EVEN. H.264 in yuv420p cannot encode an
              odd width or height, and a stage scaled to fit a window lands on
              an odd number about half the time -- which fails at the encoder,
              after the take.
  POOL        lists the thirty cards a seed will deal, WITHOUT playing it,
              and searches seeds for the names you want on camera. A pool
              of fringe players is a bad advert however well it is shot.

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
#recpool{position:fixed;right:12px;top:12px;bottom:58px;width:330px;z-index:99999;
  display:none;flex-direction:column;gap:8px;padding:10px;border-radius:10px;
  background:rgba(8,8,16,.94);border:1px solid rgba(255,255,255,.16);
  color:#dfe6f2;font:11.5px/1.45 'JetBrains Mono',ui-monospace,monospace}
#recpool.on{display:flex}
#recpool h4{font-size:11px;letter-spacing:.1em;text-transform:uppercase;
  opacity:.6;font-weight:600}
#recpool .row{display:flex;gap:6px}
#recpool input{flex:1;width:auto}
#recpool .out{flex:1;overflow:auto;border-top:1px solid rgba(255,255,255,.12);
  padding-top:6px}
#recpool .hit{color:#e0a13a;font-weight:700}
#recpool .sd{cursor:pointer;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.06)}
#recpool .sd:hover{color:#e0a13a}
#recpool .nm{opacity:.75}
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
    "1080x1920": [1080, 1920], "1080x1080": [1080, 1080],
    // fills the viewport exactly, so the scale is 1 and the crop is
    // recorded at native resolution with nothing thrown away
    "window": null
  };
  var S = { frame: Q.get("frame") || "1920x1080", chrome: false,
            speed: parseFloat(Q.get("speed") || "1"), rec: null,
            chunks: [], t0: 0, timer: null, source: "tab",
            fmt: Q.get("fmt") || "mp4", silent: null };

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
    var barH = document.getElementById("recbar") &&
               !document.getElementById("recbar").classList.contains("away")
                 ? 46 : 0;
    var f = FRAMES[S.frame];
    if (!f) f = [window.innerWidth, Math.max(200, window.innerHeight - barH)];
    // even only: H.264 in yuv420p cannot encode an odd dimension, and the
    // "window" preset lands on one about half the time
    f = [f[0] - (f[0] % 2), f[1] - (f[1] % 2)];
    stage.style.width = f[0] + "px";
    stage.style.height = f[1] + "px";
    var k = Math.min(window.innerWidth / f[0],
                     (window.innerHeight - barH) / f[1]);
    if (k > 1) k = 1;                 // never blow it up past native
    stage.style.transform = "translate(-50%,-50%) scale(" + k + ")";
    stage.style.marginTop = (-barH / 2) + "px";
    S.scale = k;
    S.out = [Math.round(f[0] * k), Math.round(f[1] * k)];
    S.out = [S.out[0] - (S.out[0] % 2), S.out[1] - (S.out[1] % 2)];
    var pct = document.getElementById("recscale");
    if (pct) {
      pct.textContent = Math.round(k * 100) + "%  " +
                        S.out[0] + "x" + S.out[1];
      // below 1:1 the recording loses resolution, and that is worth
      // noticing BEFORE the take rather than in the file
      pct.style.color = k < 0.999 ? "#e0a13a" : "";
    }
  }

  /* ---- recording ------------------------------------------------------
     getDisplayMedia, so the operator picks the tab and the browser draws
     the frames -- no canvas mirror of a DOM game, which would miss the
     CSS animations that are most of what makes it look alive. */
  /* Twitter/X accepts H.264 in MP4 and nothing else useful here. Chrome can
     record MP4 directly from MediaRecorder, which avoids a conversion step
     entirely; where it cannot, WebM is offered with a clear warning rather
     than a file that silently fails to upload. */
  var MP4 = ['video/mp4;codecs="avc1.640028,mp4a.40.2"',
             'video/mp4;codecs=avc1', 'video/mp4'];
  var WEBM = ['video/webm;codecs="vp9,opus"', 'video/webm;codecs=vp9',
              'video/webm;codecs=vp8', 'video/webm'];

  function pickType(pref) {
    var lists = pref === "webm" ? [WEBM, MP4] : [MP4, WEBM];
    for (var l = 0; l < lists.length; l++)
      for (var i = 0; i < lists[l].length; i++)
        if (window.MediaRecorder && MediaRecorder.isTypeSupported(lists[l][i]))
          return lists[l][i];
    return "";
  }

  /* A SILENT BUT REAL AUDIO TRACK.
     A screen capture has no audio, and Twitter rejects most audio-less MP4s
     at processing -- the upload appears to work and the video never plays.
     An oscillator through a zero gain node produces a genuine encoded track
     carrying silence, which satisfies the muxer and the platform without
     making a sound. */
  function silentTrack() {
    try {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      var ctx = new AC();
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      gain.gain.value = 0;                       // inaudible, still encoded
      var dst = ctx.createMediaStreamDestination();
      osc.connect(gain).connect(dst);
      osc.start();
      S.silent = { ctx: ctx, osc: osc };
      return dst.stream.getAudioTracks()[0] || null;
    } catch (e) { return null; }
  }

  function stopSilent() {
    if (!S.silent) return;
    try { S.silent.osc.stop(); S.silent.ctx.close(); } catch (e) {}
    S.silent = null;
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
    /* selfBrowserSurface:"include" is the whole reason this works.
       getDisplayMedia defaults it to "exclude" when preferCurrentTab is not
       set, so Chrome offers every tab EXCEPT the calling one -- the only one
       worth recording here. preferCurrentTab then puts it first, or picks it
       outright, instead of making the operator hunt for it every take.
       Unknown dictionary members are ignored rather than thrown, so a browser
       that has not implemented these still gets a working plain capture. */
    var opts = { video: { frameRate: 60 }, audio: false };
    if (S.source === "tab") {
      opts.preferCurrentTab = true;
      opts.selfBrowserSurface = "include";
      opts.surfaceSwitching = "exclude";
    } else {
      opts.selfBrowserSurface = "include";   // still offer it, just do not force it
    }
    var stream;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia(opts);
    } catch (e) { note("Capture cancelled."); return; }
    var type = pickType(S.fmt);
    if (!type) { note("No MediaRecorder codec available."); return; }
    var isMp4 = type.indexOf("mp4") >= 0;
    if (S.fmt === "mp4" && !isMp4) {
      note("This browser cannot record MP4 \u2014 falling back to WebM. "
           + "Twitter will not accept it as-is; convert with ffmpeg "
           + "(the command is in the console).");
      console.log("ffmpeg -i in.webm -r 30 -c:v libx264 -pix_fmt yuv420p "
                  + "-c:a aac -shortest -movflags +faststart out.mp4");
    }

    /* REGION CAPTURE. Without this the file is the whole tab: the stage
       letterboxed in the middle, the toolbar along the bottom, and a
       resolution nobody asked for. cropTo restricts the track to one
       element, so the frames ARE the stage. Self-capture only, which is
       why "This tab" is the default source. */
    var track = stream.getVideoTracks()[0];
    S.cropped = false;
    if (window.CropTarget && CropTarget.fromElement && track.cropTo) {
      try {
        await track.cropTo(await CropTarget.fromElement(stage));
        S.cropped = true;
      } catch (e) { S.cropped = false; }
    }
    // the toolbar and the note sit outside the stage, so a cropped take
    // never sees them -- but an uncropped one would, so hide them anyway
    document.getElementById("recbar").classList.add("away");
    fit();
    // attach the silent track to the SAME stream the recorder sees
    var quiet = silentTrack();
    if (quiet) stream.addTrack(quiet);
    S.chunks = [];
    S.rec = new MediaRecorder(stream, { mimeType: type,
                                        videoBitsPerSecond: 12000000,
                                        audioBitsPerSecond: 128000 });
    S.rec.ondataavailable = function (e) {
      if (e.data && e.data.size) S.chunks.push(e.data);
    };
    S.rec.onstop = function () {
      stream.getTracks().forEach(function (t) { t.stop(); });
      var blob = new Blob(S.chunks, { type: type });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "dream-team-" + S.frame + "-" + Date.now() +
                   (isMp4 ? ".mp4" : ".webm");
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
      note("Saved " + a.download);
    };
    // If the operator ends the share from the browser's own bar rather
    // than this one, stop cleanly instead of recording a dead track.
    track.addEventListener("ended", function () {
      if (S.rec && S.rec.state === "recording") stop();
    });
    S.rec.start(1000);
    S.t0 = Date.now();
    S.timer = setInterval(tick, 500);
    document.getElementById("recbtn").textContent = "Stop";
    document.getElementById("recbtn").classList.add("rec");
    document.getElementById("recdot").classList.add("on");
    var g = (track.getSettings && track.getSettings()) || {};
    note(S.cropped
      ? "Recording the stage only \u2014 " + (g.width || S.out[0]) + "x" +
        (g.height || S.out[1]) + (isMp4 ? " MP4" : " WebM") +
        (quiet ? " + silent audio" : " (NO audio track -- Twitter may reject)") +
        ". Toolbar hidden; H brings it back."
      : "Recording the WHOLE TAB \u2014 this browser has no Region Capture, "
        + "so the file will include everything around the game and need "
        + "cropping afterwards.");
  }

  function stop() {
    document.getElementById("recbar").classList.remove("away");
    fit();
    if (S.rec && S.rec.state !== "inactive") S.rec.stop();
    S.rec = null;
    stopSilent();
    clearInterval(S.timer);
    document.getElementById("recbtn").textContent = "Record";
    document.getElementById("recbtn").classList.remove("rec");
    document.getElementById("recdot").classList.remove("on");
  }

  /* ---- pool inspection ------------------------------------------------
     dtBuildPool is deterministic given a generator, and dtBuildOpponent
     takes no randomness at all, so a pool can be built and read WITHOUT
     playing it. That is what makes searching for a good seed possible
     instead of dealing games until one looks right.

     The derivation has to match dtStart exactly or the preview lies.
     dtStart does NOT use the seeded generator directly: with Math.random
     swapped it draws ONE value to make its own `seed`, then builds the
     pool from dtRng(that). Reproduced here in the same order. */
  function poolForSeed(n) {
    if (typeof window.dtRng !== "function" ||
        typeof window.dtBuildPool !== "function" ||
        typeof window.dtBuildOpponent !== "function") return null;
    var g = window.dtRng((n >>> 0) || 1);
    var inner = (g() * 0xFFFFFFFF) >>> 0;
    var rng = window.dtRng(inner);
    var realRandom = Math.random;
    Math.random = rng;                 // anything downstream stays in step
    try {
      var opp = window.dtBuildOpponent();
      var pool = window.dtBuildPool(rng, opp);
      return (pool && pool.entries) ? pool.entries : null;
    } catch (e) { return null; }
    finally { Math.random = realRandom; }
  }

  // Names worth having on camera. Only a default -- the box takes anything.
  var MARQUEE = ["Michael Jordan", "Kareem Abdul-Jabbar", "LeBron James",
    "Magic Johnson", "Larry Bird", "Wilt Chamberlain", "Bill Russell",
    "Shaquille O'Neal", "Tim Duncan", "Kobe Bryant", "Hakeem Olajuwon",
    "Stephen Curry", "Nikola Jokic", "Oscar Robertson", "Jerry West",
    "Charles Barkley", "Karl Malone", "Dirk Nowitzki", "Kevin Durant",
    "Moses Malone", "David Robinson", "Julius Erving", "Giannis Antetokounmpo"];

  function wanted() {
    var v = (document.getElementById("recwant").value || "").trim();
    if (!v) return MARQUEE;
    return v.split(",").map(function (x) { return x.trim(); })
            .filter(Boolean);
  }

  function norm(s) {
    return (s || "").toLowerCase()
      .normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z ]/g, "").trim();
  }

  function showPool(n) {
    var out = document.getElementById("recout");
    var e = poolForSeed(n);
    // An EMPTY pool is the same situation as a missing one: dtBuildPool
    // exists from the first byte of the page but returns nothing until
    // data.bin has parsed. Reporting "0 cards" made a still-loading page
    // look like a broken seed.
    if (!e || !e.length) {
      out.innerHTML = "<div>No pool yet \u2014 the game data is still " +
                      "loading. Wait for the board to appear, then try " +
                      "again.</div>";
      return;
    }
    var want = wanted().map(norm);
    var html = "<div><b>seed " + n + "</b> \u2014 " + e.length + " cards</div>";
    e.forEach(function (x) {
      var hit = want.indexOf(norm(x.name)) >= 0;
      html += '<div class="' + (hit ? "hit" : "nm") + '">' +
              (hit ? "\u2605 " : "\u00b7 ") + x.name +
              '  <span style="opacity:.5">' + (x.season || "") + "</span></div>";
    });
    out.innerHTML = html;
  }

  /* Chunked so the tab stays responsive: a few hundred pools is not free,
     and a frozen page during a recording session is worse than a slow one.
     realTimeout, not the wrapped one -- the speed dial must not slow this. */
  function findSeeds(from, count, per) {
    var out = document.getElementById("recout");
    var want = wanted().map(norm);
    var results = [];
    var i = 0;
    function chunk() {
      var end = Math.min(i + 25, count);
      for (; i < end; i++) {
        var n = from + i;
        var e = poolForSeed(n);
        if (!e) continue;
        var hits = [];
        e.forEach(function (x) {
          if (want.indexOf(norm(x.name)) >= 0) hits.push(x.name);
        });
        if (hits.length) results.push({ seed: n, hits: hits });
      }
      out.innerHTML = "<div>scanned " + i + " / " + count + "\u2026</div>";
      if (i < count) { realTimeout(chunk, 0); return; }
      results.sort(function (a, b) { return b.hits.length - a.hits.length ||
                                            a.seed - b.seed; });
      if (!results.length) {
        out.innerHTML = "<div>No seed in that range has any of those names. " +
                        "Widen the range, or check the spelling against the " +
                        "list a Pool preview shows.</div>";
        return;
      }
      var html = "<div><b>" + results.length + " seeds</b> with a match, " +
                 "best first. Click one to use it.</div>";
      results.slice(0, per).forEach(function (r) {
        html += '<div class="sd" data-seed="' + r.seed + '">' +
                '<b>seed ' + r.seed + '</b> \u2014 ' + r.hits.length +
                ': <span class="hit">' + r.hits.join(", ") + "</span></div>";
      });
      out.innerHTML = html;
      Array.prototype.forEach.call(out.querySelectorAll("[data-seed]"),
        function (el) {
          el.onclick = function () {
            document.getElementById("recseed").value = el.dataset.seed;
            showPool(parseInt(el.dataset.seed, 10));
            note("Seed " + el.dataset.seed + " staged. Apply to reload with it.");
          };
        });
    }
    chunk();
  }

  function poolPanel() {
    var p = document.createElement("div");
    p.id = "recpool";
    p.innerHTML =
      "<h4>Pool finder</h4>" +
      '<div class="row"><input id="recwant" placeholder="names, comma separated ' +
        '(blank = marquee)"></div>' +
      '<div class="row">' +
        '<input id="recfrom" placeholder="from" value="1" style="max-width:70px">' +
        '<input id="reccount" placeholder="how many" value="400" style="max-width:80px">' +
        '<button id="recfind">Find</button></div>' +
      '<div class="row"><button id="recpeek">Preview current seed</button></div>' +
      '<div class="out" id="recout"><div style="opacity:.6">Blank names box ' +
        'searches for ' + MARQUEE.length + ' marquee players.</div></div>';
    document.body.appendChild(p);
    document.getElementById("recpeek").onclick = function () {
      var v = parseInt(document.getElementById("recseed").value, 10);
      if (!v) { note("Put a seed in the toolbar box first."); return; }
      showPool(v);
    };
    document.getElementById("recfind").onclick = function () {
      findSeeds(parseInt(document.getElementById("recfrom").value, 10) || 1,
                parseInt(document.getElementById("reccount").value, 10) || 400,
                12);
    };
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
      '<span class="lbl">format</span><select id="recfmt">' +
        '<option value="mp4">MP4 (Twitter)</option>' +
        '<option value="webm">WebM</option></select>' +
      '<span class="lbl">source</span><select id="recsrc">' +
        '<option value="tab">This tab</option>' +
        '<option value="pick">Choose\u2026</option></select>' +
      '<span class="lbl">speed</span><select id="recspeed">' +
        '<option value="1">1x</option><option value="1.5">1.5x</option>' +
        '<option value="2">2x</option><option value="3">3x</option>' +
        '<option value="0.75">0.75x</option></select>' +
      '<button id="recchrome">Hide chrome</button>' +
      '<button id="recpoolbtn">Pool</button>' +
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
    document.getElementById("recfmt").value = S.fmt;
    document.getElementById("recfmt").onchange = function (e) {
      S.fmt = e.target.value;
      var t = pickType(S.fmt);
      note(S.fmt === "mp4"
        ? (t.indexOf("mp4") >= 0
            ? "MP4 with a silent audio track \u2014 uploads to Twitter as-is."
            : "This browser cannot record MP4; it will produce WebM and need "
              + "converting before Twitter accepts it.")
        : "WebM. Twitter does NOT accept this format.");
    };
    document.getElementById("recsrc").onchange = function (e) {
      S.source = e.target.value;
      note(S.source === "tab"
        ? "Will capture this tab directly."
        : "Will let you pick a surface. Chrome hides the current tab unless "
          + "\"This tab\" is selected.");
    };
    document.getElementById("recspeed").onchange = function (e) {
      S.speed = parseFloat(e.target.value) || 1;
      note("Speed " + S.speed + "x applies to the next reveal.");
    };
    document.getElementById("recpoolbtn").onclick = function () {
      var p = document.getElementById("recpool");
      p.classList.toggle("on");
      this.classList.toggle("on", p.classList.contains("on"));
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
      if (e.key === "h" || e.key === "H") {
        d.classList.toggle("away");
        fit();                 // the stage grows into the space the bar frees
      }
    });
  }

  function go() {
    if (!build()) { realTimeout(go, 60); return; }
    bar();
    poolPanel();
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
