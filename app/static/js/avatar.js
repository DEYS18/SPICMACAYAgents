/* The assistant's face: a woman in a red-bordered cream saree greeting with folded hands (namaste).
   States: idle (breathes, blinks), listening (tilts her head), thinking (looks up), speaking (mouth follows the voice).
   While the server voice plays, the mouth follows the loudness of the actual audio, decoded separately so playback
   itself is never rerouted; for the browser voice it follows a natural speaking rhythm and the word boundaries.
   Every avatar on the page (rail, welcome, the floating chip) shows the same state. */
(function (global) {
  'use strict';
  let uid = 0;
  const reduced = () => global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function svg(id) {
    return `
<svg class="smv" viewBox="0 0 200 200" role="img" aria-label="The assistant, greeting you with folded hands" focusable="false">
  <defs>
    <radialGradient id="bg${id}" cx="50%" cy="38%" r="70%"><stop offset="0" stop-color="#FFF8E6"/><stop offset=".62" stop-color="#FCE7B4"/><stop offset="1" stop-color="#F3C969"/></radialGradient>
    <clipPath id="clip${id}"><circle cx="100" cy="100" r="98"/></clipPath>
    <linearGradient id="skin${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#C98D63"/><stop offset="1" stop-color="#B97A50"/></linearGradient>
  </defs>
  <g class="smv-clip" clip-path="url(#clip${id})">
    <circle class="smv-bg" cx="100" cy="100" r="98" fill="url(#bg${id})"/>
    <circle class="smv-halo" cx="100" cy="82" r="56" fill="none" stroke="#E9A800" stroke-width="1.6" stroke-dasharray="2 5" opacity=".7"/>
    <g transform="translate(0,-14)"><g class="smv-body">
      <!-- saree: cream with a sindoor border, blouse in kumkum -->
      <path d="M22 206 C26 168 44 150 74 141 L100 146 L126 141 C156 150 174 168 178 206 Z" fill="#FBF3E2"/>
      <path d="M40 206 C44 176 56 158 76 148 L84 151 C66 162 56 182 54 206 Z" fill="#7A1018"/>
      <path d="M160 206 C156 176 144 158 124 148 L116 151 C134 162 144 182 146 206 Z" fill="#7A1018"/>
      <path class="smv-pallu" d="M124 141 C150 149 168 166 176 206 L150 206 C142 176 128 160 108 150 Z" fill="#A3161E"/>
      <path d="M126 145 C150 154 165 170 171 206" fill="none" stroke="#E9A800" stroke-width="2.2"/>
      <path d="M111 152 C130 162 143 180 149 206" fill="none" stroke="#E9A800" stroke-width="1.4"/>
      <!-- neck -->
      <path d="M88 104 L112 104 L114 140 C108 147 92 147 86 140 Z" fill="url(#skin${id})"/>
      <path d="M86 136 C93 143 107 143 114 136 L114 140 C108 147 92 147 86 140 Z" fill="#A86C44" opacity=".55"/>
      <path d="M84 141 C92 151 108 151 116 141" fill="none" stroke="#E9A800" stroke-width="2"/>
      <circle cx="100" cy="149.5" r="2.6" fill="#E9A800"/>
      <path d="M22 206 L178 206 L178 230 L22 230 Z" fill="#FBF3E2"/>
    </g></g>
    <g transform="translate(0,-9)"><g class="smv-head">
      <!-- hair behind, bun with jasmine -->
      <path d="M65 84 C61 50 80 34 102 34 C126 34 142 52 137 86 C135 95 131 101 125 104 L75 104 C69 100 66 93 65 84 Z" fill="#231410"/>
      <circle cx="136" cy="64" r="15" fill="#231410"/>
      <g fill="#FFFDF5" stroke="#E8DFC8" stroke-width=".6">
        <circle cx="127" cy="50" r="3.2"/><circle cx="134" cy="47.5" r="3.2"/><circle cx="141" cy="49" r="3.2"/><circle cx="147" cy="54" r="3.2"/>
        <circle cx="150" cy="61" r="3.2"/><circle cx="150" cy="68.5" r="3.2"/><circle cx="147" cy="75.5" r="3.2"/>
      </g>
      <!-- ears and jhumkas -->
      <ellipse cx="70" cy="86" rx="5.5" ry="8" fill="#B97A50"/><ellipse cx="130" cy="86" rx="5.5" ry="8" fill="#B97A50"/>
      <g class="smv-jhumka"><path d="M66 96 L74 96 L76 104 C74 107 66 107 64 104 Z" fill="#E9A800"/><circle cx="70" cy="93.5" r="2" fill="#E9A800"/><circle cx="70" cy="107.5" r="1.4" fill="#A3161E"/></g>
      <g class="smv-jhumka"><path d="M126 96 L134 96 L136 104 C134 107 126 107 124 104 Z" fill="#E9A800"/><circle cx="130" cy="93.5" r="2" fill="#E9A800"/><circle cx="130" cy="107.5" r="1.4" fill="#A3161E"/></g>
      <!-- face -->
      <path d="M71 78 C71 56 84 46 100 46 C116 46 129 56 129 78 C129 99 117 117 100 117 C83 117 71 99 71 78 Z" fill="url(#skin${id})"/>
      <!-- hair in front: centre parting, sindoor in the parting -->
      <path d="M70 80 C68 56 82 40 100 40 C118 40 132 56 130 80 C126 64 116 54 101 52 C88 54 76 63 70 80 Z" fill="#231410"/>
      <path d="M100 41 L100 51" stroke="#A3161E" stroke-width="2.2" stroke-linecap="round"/>
      <!-- brows, eyes, bindi, nose, cheeks -->
      <g class="smv-brows" fill="none" stroke="#2A1710" stroke-width="2.1" stroke-linecap="round">
        <path d="M80 72 C84 68.5 90 68.5 94 70.5"/><path d="M106 70.5 C110 68.5 116 68.5 120 72"/>
      </g>
      <g class="smv-eyes">
        <g class="smv-eye"><path d="M80.5 80 C83.5 76.5 90.5 76.5 93.5 80 C90.5 83 83.5 83 80.5 80 Z" fill="#FFFDF8"/><circle class="smv-pupil" cx="87" cy="79.8" r="2.9" fill="#2A1710"/><circle class="smv-pupil" cx="88" cy="78.8" r=".9" fill="#fff"/><path d="M80 79.6 C83.5 75.6 90.5 75.6 94 79.6" fill="none" stroke="#2A1710" stroke-width="1.5" stroke-linecap="round"/></g>
        <g class="smv-eye"><path d="M106.5 80 C109.5 76.5 116.5 76.5 119.5 80 C116.5 83 109.5 83 106.5 80 Z" fill="#FFFDF8"/><circle class="smv-pupil" cx="113" cy="79.8" r="2.9" fill="#2A1710"/><circle class="smv-pupil" cx="114" cy="78.8" r=".9" fill="#fff"/><path d="M106 79.6 C109.5 75.6 116.5 75.6 120 79.6" fill="none" stroke="#2A1710" stroke-width="1.5" stroke-linecap="round"/></g>
      </g>
      <circle cx="100" cy="66" r="2.7" fill="#A3161E"/>
      <path d="M100 82 C99 88 97.5 91 96.5 93 C98.5 94.2 101.5 94.2 103.5 93" fill="none" stroke="#9A5F3A" stroke-width="1.5" stroke-linecap="round"/>
      <ellipse cx="82" cy="94" rx="6" ry="3.6" fill="#E08E78" opacity=".32"/><ellipse cx="118" cy="94" rx="6" ry="3.6" fill="#E08E78" opacity=".32"/>
      <!-- mouth: a smile at rest; while speaking an opening that follows the voice -->
      <g class="smv-mouth">
        <path class="smv-smile" d="M91.5 101.5 C95.5 105.5 104.5 105.5 108.5 101.5" fill="none" stroke="#8E2F2A" stroke-width="2.2" stroke-linecap="round"/>
        <g class="smv-open">
          <path d="M92.5 101 C95 99.4 105 99.4 107.5 101 C107.5 107 104 110.5 100 110.5 C96 110.5 92.5 107 92.5 101 Z" fill="#5E1A18"/>
          <path d="M95.5 107.6 C98 106 102 106 104.5 107.6 C103 109.6 97 109.6 95.5 107.6 Z" fill="#C8584F"/>
          <path d="M94 101.3 C97.5 102.3 102.5 102.3 106 101.3" fill="none" stroke="#FFF7EE" stroke-width="1.4" stroke-linecap="round"/>
        </g>
      </g>
    </g></g>
    <!-- folded hands (namaste) with bangles -->
    <g transform="translate(0,-17)"><g class="smv-hands">
      <path d="M40 206 C52 190 72 182 92 178 L94 190 C78 194 64 200 58 206 Z" fill="url(#skin${id})"/>
      <path d="M160 206 C148 190 128 182 108 178 L106 190 C122 194 136 200 142 206 Z" fill="url(#skin${id})"/>
      <path d="M77 181 L80 192" stroke="#E9A800" stroke-width="3.2" stroke-linecap="round"/><path d="M71 184 L74 195" stroke="#A3161E" stroke-width="3" stroke-linecap="round"/>
      <path d="M123 181 L120 192" stroke="#E9A800" stroke-width="3.2" stroke-linecap="round"/><path d="M129 184 L126 195" stroke="#A3161E" stroke-width="3" stroke-linecap="round"/>
      <path d="M100 141 C106 145 110.5 156 110.5 168 C110.5 178 108 186 104 190 L96 190 C92 186 89.5 178 89.5 168 C89.5 156 94 145 100 141 Z" fill="url(#skin${id})"/>
      <path d="M100 143 L100 189" stroke="#9A5F3A" stroke-width="1.3" stroke-linecap="round"/>
      <path d="M95 160 C96.5 158.5 98.5 158.5 100 159.5 M105 160 C103.5 158.5 101.5 158.5 100 159.5" fill="none" stroke="#9A5F3A" stroke-width="1" opacity=".7"/>
      <path d="M91.5 171 C93 175 95.5 177.5 99 178" fill="none" stroke="#9A5F3A" stroke-width="1.2" stroke-linecap="round" opacity=".8"/>
      <path d="M108.5 171 C107 175 104.5 177.5 101 178" fill="none" stroke="#9A5F3A" stroke-width="1.2" stroke-linecap="round" opacity=".8"/>
      <path d="M40 206 L58 206 L60 226 L36 226 Z M160 206 L142 206 L140 226 L164 226 Z" fill="url(#skin${id})"/>
    </g></g>
    <g class="smv-think" fill="#A3161E"><circle cx="150" cy="34" r="3"/><circle cx="160" cy="34" r="3"/><circle cx="170" cy="34" r="3"/></g>
  </g>
  <circle class="smv-ring" cx="100" cy="100" r="97" fill="none" stroke="#E9A800" stroke-width="3"/>
</svg>`;
  }

  const avatars = new Set();
  let state = 'idle', open = 0, raf = 0, talk = null;

  function apply() { avatars.forEach(a => { a.dataset.state = state; a.style.setProperty('--open', open.toFixed(3)); }); }

  function mount(host, opts) {
    if (!host) return null;
    host.innerHTML = svg(++uid);
    host.classList.add('smv-host');
    if (opts && opts.bow) host.classList.add('smv-bow');
    avatars.add(host);
    apply();
    return host;
  }

  // Loudness envelope of the reply audio: RMS per 40 ms, normalised.
  async function envelope(arrayBuffer) {
    const OAC = global.OfflineAudioContext || global.webkitOfflineAudioContext;
    if (!OAC) return null;
    const ctx = new OAC(1, 44100, 44100);
    const buf = await new Promise((res, rej) => { const p = ctx.decodeAudioData(arrayBuffer, res, rej); if (p && p.catch) p.catch(rej); });
    const data = buf.getChannelData(0), hop = Math.max(1, Math.round(buf.sampleRate * 0.04)), out = [];
    let peak = 0;
    for (let i = 0; i < data.length; i += hop) {
      let s = 0;
      const end = Math.min(data.length, i + hop);
      for (let j = i; j < end; j++) s += data[j] * data[j];
      const v = Math.sqrt(s / (end - i));
      out.push(v); if (v > peak) peak = v;
    }
    return peak ? { hop: 0.04, values: out.map(v => v / peak) } : null;
  }

  function loop() {
    cancelAnimationFrame(raf);
    let target = 0, nextAt = 0;
    const step = now => {
      if (!talk) { open = 0; apply(); return; }
      let goal;
      if (talk.audio && talk.env && !talk.audio.paused) {
        const v = talk.env.values[Math.floor(talk.audio.currentTime / talk.env.hop)] || 0;
        goal = v < 0.12 ? 0 : Math.min(1, 0.25 + v * 0.95);
      } else {
        if (now >= nextAt) {                                  // syllables of 90-170 ms, a short gap now and then
          const gap = Math.random() < 0.16;
          target = gap ? 0 : 0.35 + Math.random() * 0.65;
          nextAt = now + (gap ? 120 + Math.random() * 160 : 90 + Math.random() * 80);
        }
        if (talk.boundary && now - talk.boundary < 90) target = Math.max(target, 0.9);
        goal = target;
      }
      open += (goal - open) * (goal > open ? 0.55 : 0.35);
      apply();
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
  }

  const api = {
    mount,
    setState(s) {
      if (talk && s !== 'speaking') return;                   // speaking wins until it ends
      state = s || 'idle';
      apply();
    },
    // info: {audio, buffer} for the server voice, {utterance} for the browser voice
    startSpeaking(info) {
      talk = { audio: info && info.audio, env: null, boundary: 0 };
      state = 'speaking';
      apply();
      if (reduced()) { open = 0.5; apply(); return; }
      const mine = talk;
      if (info && info.buffer) envelope(info.buffer).then(e => { if (talk === mine) talk.env = e; }).catch(() => {});
      if (info && info.utterance) info.utterance.addEventListener('boundary', () => { if (talk === mine) talk.boundary = performance.now(); });
      loop();
    },
    stopSpeaking() {
      talk = null; cancelAnimationFrame(raf); open = 0; state = 'idle'; apply();
    },
    get state() { return state; }
  };
  global.SMAvatar = api;
})(window);
