// Paper style kit for video scenes (V-917). make.py injects this before the scene runs.
// Every function is pure in t: it sets attributes from the given time and keeps no state,
// so seeking backwards or rendering frames in parallel produces identical pictures.
(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const ease = p => { p = clamp(p); return p * p * (3 - 2 * p); };
  const mk = (parent, name, attrs = {}) => {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.append(e);
    return e;
  };
  const DEFS = `
<filter id="paper-torn" x="-5%" y="-5%" width="110%" height="110%"><feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="3" seed="7"/><feDisplacementMap in="SourceGraphic" scale="22"/></filter>
<filter id="paper-bristle" x="-10%" y="-30%" width="120%" height="160%"><feTurbulence type="fractalNoise" baseFrequency="0.02 0.25" numOctaves="2" seed="3"/><feDisplacementMap in="SourceGraphic" scale="70"/></filter>
<filter id="paper-wobble"><feTurbulence type="fractalNoise" baseFrequency="0.018" numOctaves="2" seed="11"/><feDisplacementMap in="SourceGraphic" scale="5"/></filter>
<filter id="paper-grain"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="5"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="table" tableValues="0 .55"/></feComponentTransfer></filter>
<radialGradient id="paper-vignette" cx=".5" cy=".45" r=".75"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></radialGradient>
<marker id="paper-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#0e5e9c"/></marker>
<marker id="paper-arrow-orange" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#c9551b"/></marker>`;

  const Paper = {
    BLUE: '#0e5e9c', BLUE_TINT: '#d6e8f4', ORANGE: '#c9551b', ORANGE_TINT: '#fde4d0',
    INK: '#16171b', MUTED: '#6b7280', CELL: '#eef0f3', BG: '#f6f7f9', LINE: '#d9dce3',
    clamp, ease,

    /** Add the shared filters, gradients and arrow markers to the scene SVG once. */
    install(svg = document.getElementById('stage')) {
      if (svg.querySelector('#paper-torn')) return;
      const defs = mk(null, 'defs');
      defs.innerHTML = DEFS;
      svg.prepend(defs);
    },

    /** Turn <g id> into a painted picture inside box {x, y, w, h}: torn paper edge, grain,
     *  vignette, slight hand-drawn wobble. Its children go into a camera group.
     *  Returns {cam, brush}; pass the result to Paper.brush and Paper.camera. */
    picture(g, box, {scene} = {}) {
      if (typeof g === 'string') g = document.getElementById(g);
      if (g._paper) return g._paper;
      const svg = g.ownerSVGElement;
      Paper.install(svg);
      if (scene) {
        const known = Paper.SCENES[scene];
        if (!known) throw new Error(`Paper: unknown scene "${scene}"; known: ${Object.keys(Paper.SCENES).join(', ')}`);
        g.innerHTML = known.svg;
      }
      const id = g.id || `pic${Math.random().toString(36).slice(2, 8)}`;
      const defs = svg.querySelector('defs');
      const torn = mk(defs, 'mask', {id: `${id}-torn`});
      mk(torn, 'rect', {x: box.x, y: box.y, width: box.w, height: box.h, fill: '#fff', filter: 'url(#paper-torn)'});
      const reveal = mk(defs, 'mask', {id: `${id}-brush`});
      const bristle = mk(reveal, 'g', {filter: 'url(#paper-bristle)'});
      // a roller stroke that sweeps across, then zigzags down: each band covers ~1/4 of the height
      const band = box.h / 4, x0 = box.x - 60, x1 = box.x + box.w + 60;
      let d = `M${x0} ${box.y + band * .5}H${x1}`;
      for (let k = 1; k < 5; k++) d += `L${x0} ${box.y + band * (k + .5)}H${x1}`;
      const brush = mk(bristle, 'path', {d, fill: 'none', stroke: '#fff', 'stroke-width': band * 1.45, 'stroke-linejoin': 'round'});
      const cam = mk(null, 'g', {filter: 'url(#paper-wobble)'});
      cam.append(...g.childNodes);
      const pad = 40;
      mk(cam, 'rect', {x: box.x - pad, y: box.y - pad, width: box.w + 2 * pad, height: box.h + 2 * pad,
        filter: 'url(#paper-grain)', style: 'mix-blend-mode:multiply', opacity: .55});
      mk(cam, 'rect', {x: box.x - pad, y: box.y - pad, width: box.w + 2 * pad, height: box.h + 2 * pad, fill: 'url(#paper-vignette)'});
      const inner = mk(g, 'g', {mask: `url(#${id}-torn)`});
      inner.append(cam);
      g.setAttribute('mask', `url(#${id}-brush)`);
      g._paper = {cam, brush, box, scene};
      return g._paper;
    },

    /** Bundled opening/closing scenes (scripts/video_artifact/scenes/, injected by make.py):
     *  {id: {title, fits, screen: [x, y, w, h], svg}}. */
    SCENES: window.__PAPER_SCENES || {},

    /** Camera view for a bundled scene: its screen centre moves to `to` and the screen grows
     *  until a diagram `width` wide fills it. Use with camera(), miniature() and mini(). */
    view(scene, {to = [640, 235], width = 1100} = {}) {
      const [x, y, w, h] = Paper.SCENES[scene].screen;
      return {from: [x + w / 2, y + h / 2], to, scale: width / w};
    },

    /** Put a shrunken <use> copy of the diagram `refId` on the picture's screen, so the push-in
     *  ends exactly on the real diagram. Returns the copy's group (fade it in with opacity). */
    mini(pic, refId, view) {
      const slot = pic.cam.querySelector('.paper-mini') || mk(pic.cam, 'g');
      mk(slot, 'use', {href: `#${refId}`, transform: Paper.miniature(view)});
      return slot;
    },

    /** Small life in a picture: clock hands (.paper-hand-h/.paper-hand-m with data-c="x,y")
     *  turn and steam (.paper-steam) drifts. Pure in t. */
    live(pic, t) {
      for (const [cls, speed, start] of [['.paper-hand-m', 9, 300], ['.paper-hand-h', .75, -40]])
        for (const e of pic.cam.querySelectorAll(cls)) e.setAttribute('transform', `rotate(${(start + t * speed).toFixed(2)} ${e.dataset.c.replace(',', ' ')})`);
      for (const e of pic.cam.querySelectorAll('.paper-steam')) {
        e.setAttribute('transform', `translate(${(Math.sin(t * 1.7) * 3).toFixed(2)} ${(-((t * 6) % 10)).toFixed(2)})`);
        e.setAttribute('opacity', (.55 + .3 * Math.sin(t * 2.3)).toFixed(3));
      }
    },

    /** Frame check (V-935): every element with data-on="<support id>" must rest on its support —
     *  its bottom inside the support's vertical span and its centre above the support's width.
     *  make.py fails the build on any issue: a lamp in mid-air reads as a mistake to every viewer. */
    supportIssues(root = document) {
      const issues = [];
      for (const e of root.querySelectorAll('[data-on]')) {
        const s = root.getElementById ? root.getElementById(e.dataset.on) : document.getElementById(e.dataset.on);
        if (!s) { issues.push(`${e.dataset.on}: опора не найдена`); continue; }
        // экранные рамки: учитывают transform у самого предмета и у его предков
        const a = e.getBoundingClientRect(), b = s.getBoundingClientRect(), bottom = a.y + a.height, cx = a.x + a.width / 2, tol = 6;
        if (bottom < b.y - tol || bottom > b.y + b.height + tol || cx < b.x || cx > b.x + b.width)
          issues.push(`предмет над «${e.dataset.on}» висит или стоит мимо: низ ${bottom.toFixed(0)}, опора y ${b.y.toFixed(0)}…${(b.y + b.height).toFixed(0)}, ` +
            `центр x ${cx.toFixed(0)}, опора x ${b.x.toFixed(0)}…${(b.x + b.width).toFixed(0)}`);
      }
      return issues;
    },

    /** Brush reveal: the picture appears in roller strokes between t0 and t0 + dur. */
    brush(pic, t, t0 = 0, dur = 1.2, {out = false} = {}) {
      const L = pic.brush._len ??= pic.brush.getTotalLength();
      const q = ease((t - t0) / dur);
      pic.brush.style.strokeDasharray = L;
      // out: the same strokes wipe the picture away, starting where the reveal started
      pic.brush.style.strokeDashoffset = (out ? -L * q : L * (1 - q)).toFixed(1);
    },

    /** Camera push-in: point `from` (picture coordinates) moves to `to` (stage coordinates)
     *  while the zoom grows to `scale` between t0 and t1. Finish before the next step starts:
     *  a match cut into a flat diagram needs the zoom at rest. */
    camera(pic, t, {t0, t1, from, to = from, scale}) {
      const z = ease((t - t0) / (t1 - t0)), s = 1 + (scale - 1) * z;
      const x = from[0] + (to[0] - from[0]) * z, y = from[1] + (to[1] - from[1]) * z;
      pic.cam.setAttribute('transform',
        `translate(${x.toFixed(2)} ${y.toFixed(2)}) scale(${s.toFixed(4)}) translate(${-from[0]} ${-from[1]})`);
      return z;
    },

    /** Inverse camera mapping: a transform that shrinks a stage-space group back into the
     *  picture, so a <use> copy inside the picture lands exactly on the original after the zoom. */
    miniature({from, to = from, scale}) {
      return `translate(${from[0]} ${from[1]}) scale(${(1 / scale).toFixed(6)}) translate(${-to[0]} ${-to[1]})`;
    },

    /** Crossfade opacity 0→1 over dur seconds starting at t0. */
    fade(t, t0, dur = .45) { return ease((t - t0) / dur); },

    /** Typewriter with a block cursor: types `text` between t0 and t1, the cursor blinks after. */
    type(el, text, t, t0, t1, {cursor = true} = {}) {
      if (t < t0) { el.textContent = ''; return; }
      const n = Math.round(clamp((t - t0) / (t1 - t0)) * text.length);
      const blink = Math.floor(t * 2.2) % 2 === 0;
      el.textContent = text.slice(0, n) + (cursor && (n < text.length || blink) ? '▌' : '');
    },

    /** Hook (V-949): make.py --hook "claim with a number" shows it over the first seconds, before the
     *  voice carries the story. Numbers are tinted; it fades out over its last 0.4 s. Pure in t. */
    hook(t) {
      const h = window.__HOOK;
      if (!h) return;
      let el = document.getElementById('paper-hook');
      if (!el) {
        el = document.createElement('div');
        el.id = 'paper-hook';
        el.style.cssText = 'position:fixed;left:8%;right:8%;top:30%;transform:translateY(-50%);text-align:center;' +
          'font:800 56px/1.12 Manrope,system-ui,sans-serif;color:#16171b;background:rgba(246,247,249,.94);' +
          'padding:28px 0;border-radius:24px;box-shadow:0 6px 30px rgba(22,23,27,.18)';
        h.text.split(/(\d+(?:[.,]\d+)?\s?%?)/).forEach((part, i) => {
          const span = document.createElement('span');
          span.textContent = part;
          if (i % 2) span.style.color = Paper.ORANGE;
          el.append(span);
        });
        document.body.append(el);
      }
      el.style.opacity = (1 - ease((t - (h.until - .4)) / .4)).toFixed(3);
      el.style.visibility = t >= h.until ? 'hidden' : 'visible';
    },

    /** Video chrome of the paper theme, called by make.py after every P.seek(t):
     *  a thin progress bar at the bottom edge and a short blur when the caption changes. */
    chrome(t) {
      Paper.hook(t);
      if (document.documentElement.dataset.theme !== 'paper' || typeof P === 'undefined') return;
      let bar = document.getElementById('paper-progress');
      if (!bar) { bar = document.createElement('div'); bar.id = 'paper-progress'; document.body.append(bar); }
      bar.style.width = `${(t / P.T * 100).toFixed(3)}%`;
      const S = P.S || [0];  // a hand-written player without step starts gets only the bar
      let i = S.length - 1;
      while (i > 0 && t <= S[i]) i--;
      const cap = document.querySelector('.cap');
      if (cap) cap.style.filter = `blur(${((1 - clamp((t - S[i]) / .45)) * 4).toFixed(2)}px)`;
    },
  };
  window.Paper = Paper;
})();
