// The 16x2 LCD on the home page. Characters are real dot-matrix glyphs: each one is drawn in
// Departure Mono at its native 11 px size, sampled pixel by pixel, and every pixel becomes an LCD dot.
(function () {
  var fig = document.querySelector('[data-lcd]');
  if (!fig) return;
  var msgs = JSON.parse(fig.getAttribute('data-lcd'));
  var canvas = fig.querySelector('canvas');
  var ctx = canvas.getContext('2d');
  var bezel = fig.querySelector('.bezel');
  var input = fig.querySelector('.type-in');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var COLS = 16, ROWS = 2, CH = 11, GAP = 1, PITCH = 4, PAD = 7;
  var CW = 7, BASE = 9, W = 0, H = 0, dpr = 1;
  var ON = '#1b2905', OFF = 'rgba(27, 41, 5, 0.075)';
  var off = document.createElement('canvas');
  var octx = off.getContext('2d', { willReadFrequently: true });
  var glyphs = {};
  var FONT = '11px "Departure Mono", ui-monospace, monospace';

  function setup() {
    octx.font = FONT;
    CW = Math.max(5, Math.min(9, Math.round(octx.measureText('M').width)));
    var asc = Math.round(octx.measureText('H').actualBoundingBoxAscent || 7);
    var desc = Math.round(octx.measureText('gjpqy').actualBoundingBoxDescent || 2);
    BASE = Math.max(asc, Math.floor((CH - asc - desc) / 2) + asc);
    off.width = CW; off.height = CH;
    W = PAD * 2 + (COLS * (CW + GAP) - GAP) * PITCH;
    H = PAD * 2 + (ROWS * (CH + GAP) - GAP) * PITCH;
    dpr = Math.max(1, Math.round(window.devicePixelRatio || 1));
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.aspectRatio = W + ' / ' + H;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    glyphs = {};
  }

  function glyph(ch) {
    if (glyphs[ch]) return glyphs[ch];
    octx.clearRect(0, 0, CW, CH);
    octx.font = FONT;
    octx.fillStyle = '#000';
    octx.textBaseline = 'alphabetic';
    octx.fillText(ch, 0, BASE);
    var d = octx.getImageData(0, 0, CW, CH).data, on = new Array(CW * CH);
    for (var i = 0; i < CW * CH; i++) on[i] = d[i * 4 + 3] > 110;
    glyphs[ch] = on;
    return on;
  }

  function draw(lines, cur) {
    ctx.clearRect(0, 0, W, H);
    for (var r = 0; r < ROWS; r++) {
      var line = lines[r] || '';
      for (var c = 0; c < COLS; c++) {
        var g = glyph(line.charAt(c) || ' ');
        var showCur = cur && cur[0] === r && cur[1] === c;
        for (var py = 0; py < CH; py++) {
          for (var px = 0; px < CW; px++) {
            var lit = g[py * CW + px] || (showCur && py === CH - 1 && px < CW - 1);
            ctx.fillStyle = lit ? ON : OFF;
            ctx.fillRect(PAD + (c * (CW + GAP) + px) * PITCH, PAD + (r * (CH + GAP) + py) * PITCH, PITCH - 1, PITCH - 1);
          }
        }
      }
    }
  }

  // ---- auto mode: type each message, hold, move on ----
  var idx = 0, shown = 0, timer = null, blink = true, userUntil = 0, visible = true;
  function full(i) { return [msgs[i][0].slice(0, COLS), msgs[i][1].slice(0, COLS)]; }
  function partial(i, n) {
    var m = full(i), a = m[0].slice(0, n), b = n > m[0].length ? m[1].slice(0, n - m[0].length) : '';
    var cur = n <= m[0].length ? [0, a.length] : [1, b.length];
    return { lines: [a, b], cur: cur, done: n >= m[0].length + m[1].length };
  }
  function tick() {
    clearTimeout(timer);
    if (Date.now() < userUntil) { timer = setTimeout(tick, 400); return; }
    if (!visible) { timer = setTimeout(tick, 600); return; }
    var p = partial(idx, shown);
    blink = !blink;
    draw(p.lines, p.done ? (blink ? p.cur : null) : p.cur);
    if (!p.done) { shown++; timer = setTimeout(tick, 70 + Math.random() * 50); return; }
    if (shown < 1000) { shown = 1000; timer = setTimeout(tick, 450); return; }   // start the hold
    if (shown < 1005) { shown++; timer = setTimeout(tick, 450); return; }          // blink a few times
    idx = (idx + 1) % msgs.length; shown = 0; timer = setTimeout(tick, 250);
  }
  function show(i) {
    idx = (i + msgs.length) % msgs.length;
    userUntil = 0; input.value = '';
    if (reduce) { draw(full(idx), null); return; }
    shown = 0; tick();
  }

  // ---- buttons and typing ----
  fig.querySelector('[data-prev]').addEventListener('click', function () { show(idx - 1); });
  fig.querySelector('[data-next]').addEventListener('click', function () { show(idx + 1); });
  fig.querySelector('.board').addEventListener('click', function () { input.focus({ preventScroll: true }); });
  bezel.addEventListener('focus', function () { input.focus({ preventScroll: true }); });
  input.addEventListener('input', function () {
    var v = input.value.replace(/[\r\n]/g, '').slice(0, COLS * 2);
    input.value = v;
    userUntil = Date.now() + 9000;
    draw([v.slice(0, COLS), v.slice(COLS)], v.length >= COLS * 2 ? null : [v.length < COLS ? 0 : 1, v.length % COLS]);
  });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === 'Escape') { e.preventDefault(); show(idx + 1); if (e.key === 'Escape') input.blur(); }
  });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (es) { visible = es[0].isIntersecting; }).observe(canvas);
  }
  document.addEventListener('visibilitychange', function () { visible = !document.hidden; });

  var started = false;
  function start() {
    if (started) return;
    started = true;
    setup();
    if (reduce) draw(full(0), null); else tick();
  }
  if (document.fonts && document.fonts.load) {
    document.fonts.load(FONT).then(start, start);
    setTimeout(start, 2500);
  } else {
    start();
  }
})();
