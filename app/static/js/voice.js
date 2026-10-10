/* Voice for the APR Assistant.
   Tap the mic: it listens and stops by itself when you pause. Hold it: push-to-talk.
   Audio goes to the server, which transcribes it in the chosen language with a vocabulary of
   artist and institution names; without server speech, the browser's own recogniser is used.
   Replies can be read aloud (server voice, else the browser voice). */
(function (global) {
  'use strict';
  const LOCALES = { hi: 'hi-IN', en: 'en-IN', hinglish: 'en-IN', mr: 'mr-IN', ta: 'ta-IN', te: 'te-IN', bn: 'bn-IN', gu: 'gu-IN',
    kn: 'kn-IN', ml: 'ml-IN', pa: 'pa-IN', or: 'or-IN', as: 'as-IN', ur: 'ur-IN', auto: 'en-IN' };
  const STOP_WORDS = ['stop', 'bas', 'बस', 'ruko', 'रुको', 'cancel', 'thamba', 'थांबा'];
  const vibrate = ms => { try { if (navigator.vibrate) navigator.vibrate(ms); } catch (e) { /* not supported */ } };

  class Voice {
    constructor(o) { this.o = o; this.state = 'idle'; this.chunks = []; this.audio = null; this.sr = null; }
    get canRecord() { return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && global.MediaRecorder); }
    get canBrowserSTT() { return !!(global.SpeechRecognition || global.webkitSpeechRecognition); }
    pickMime() {
      for (const m of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']) {
        if (global.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) return m;
      }
      return '';
    }
    setState(s) { this.state = s; this.o.onState(s); }

    async start(mode) {
      if (this.state !== 'idle') return;
      this.mode = mode || 'toggle';
      this.cancelled = false;
      if (!this.o.serverSTT() || !this.canRecord) return this.startBrowserSTT();
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      } catch (e) {
        const insecure = location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1';
        this.o.onError(insecure ? 'The microphone only works on a secure (https) address.'
          : e && e.name === 'NotAllowedError' ? 'Microphone permission was refused. Allow it in the browser settings to speak.'
          : 'No microphone was found.');
        return;
      }
      const mime = this.pickMime();
      this.mime = mime || 'audio/webm';
      this.chunks = [];
      this.heard = false;
      this.recorder = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined);
      this.recorder.ondataavailable = e => { if (e.data && e.data.size) this.chunks.push(e.data); };
      this.recorder.onstop = () => this.finish();
      this.recorder.start(250);
      this.started = Date.now();
      this.setState('recording');
      this.meter();
      vibrate(15);
    }

    meter() {
      try {
        const AC = global.AudioContext || global.webkitAudioContext;
        this.ctx = new AC();
        const an = this.ctx.createAnalyser();
        an.fftSize = 1024;
        this.ctx.createMediaStreamSource(this.stream).connect(an);
        const buf = new Float32Array(an.fftSize);
        let noise = 0.008, lastVoice = Date.now();
        const tick = () => {
          if (this.state !== 'recording') return;
          an.getFloatTimeDomainData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
          const rms = Math.sqrt(sum / buf.length);
          if (!this.heard) noise = noise * 0.95 + rms * 0.05;
          if (rms > Math.max(0.018, noise * 3)) { this.heard = true; lastVoice = Date.now(); }
          this.o.onLevel(Math.min(1, rms * 9));
          const elapsed = Date.now() - this.started;
          if (this.mode === 'toggle' && this.heard && Date.now() - lastVoice > 1500) return this.stop();
          if (!this.heard && elapsed > 9000) { this.o.onError("I didn't hear anything. Tap the mic and try again."); return this.cancel(); }
          if (elapsed > 60000) return this.stop();
          this.raf = requestAnimationFrame(tick);
        };
        this.raf = requestAnimationFrame(tick);
      } catch (e) { /* the level meter is optional */ }
    }

    stop() {
      if (this.sr) { try { this.sr.stop(); } catch (e) { /* already stopped */ } return; }
      if (this.state !== 'recording') return;
      cancelAnimationFrame(this.raf);
      this.setState('processing');
      try { this.recorder.stop(); } catch (e) { this.setState('idle'); }
      this.release();
      vibrate(10);
    }

    cancel() {
      this.cancelled = true;
      if (this.sr) { try { this.sr.abort(); } catch (e) { /* ignore */ } }
      if (this.state === 'recording' && this.recorder) { try { this.recorder.stop(); } catch (e) { /* ignore */ } }
      this.release();
      this.setState('idle');
    }

    release() {
      if (this.stream) this.stream.getTracks().forEach(t => t.stop());
      this.stream = null;
      if (this.ctx) { this.ctx.close().catch(() => {}); this.ctx = null; }
      this.o.onLevel(0);
    }

    async finish() {
      if (this.cancelled) { this.setState('idle'); return; }
      const blob = new Blob(this.chunks, { type: this.mime.split(';')[0] });
      if (blob.size < 2500) { this.setState('idle'); this.o.onError('That was too short. Hold the mic a little longer.'); return; }
      const ext = this.mime.includes('mp4') ? 'm4a' : this.mime.includes('ogg') ? 'ogg' : 'webm';
      const fd = new FormData();
      fd.append('audio', blob, 'speech.' + ext);
      fd.append('language', this.o.language());
      try {
        const res = await fetch(this.o.base + '/api/assistant/voice/transcribe', { method: 'POST', body: fd, credentials: 'same-origin' });
        const j = await res.json().catch(() => ({}));
        this.setState('idle');
        if (j.success && j.text) this.result(j.text);
        else this.o.onError(j.error ? 'Voice: ' + j.error : "I couldn't make that out. Please try again.");
      } catch (e) {
        this.setState('idle');
        this.o.onError('The voice service is not reachable right now.');
      }
    }

    startBrowserSTT() {
      const SR = global.SpeechRecognition || global.webkitSpeechRecognition;
      if (!SR) { this.o.onError('Voice input is not available in this browser. Try Chrome, or type instead.'); return; }
      const sr = new SR();
      this.sr = sr;
      sr.lang = LOCALES[this.o.language()] || 'en-IN';
      sr.interimResults = true;
      sr.continuous = this.mode === 'hold';
      let finalText = '';
      sr.onresult = e => {
        let interim = '';
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const t = e.results[i][0].transcript;
          if (e.results[i].isFinal) finalText += t; else interim += t;
        }
        this.o.onInterim((finalText + interim).trim());
      };
      sr.onerror = e => {
        if (e.error === 'no-speech') this.o.onError("I didn't hear anything.");
        else if (e.error !== 'aborted') this.o.onError('Voice input stopped (' + e.error + ').');
      };
      sr.onend = () => {
        this.sr = null;
        this.setState('idle');
        if (!this.cancelled && finalText.trim()) this.result(finalText.trim());
      };
      try { sr.start(); this.started = Date.now(); this.setState('recording'); vibrate(15); }
      catch (e) { this.sr = null; this.o.onError('Could not start voice input.'); }
    }

    result(text) {
      const t = text.trim();
      if (STOP_WORDS.includes(t.toLowerCase().replace(/[.!।?]/g, '').trim())) { this.o.onStopWord(); return; }
      this.o.onResult(t);
    }

    async speak(text, lang) {
      const clean = String(text || '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/https?:\/\/\S+/g, '')
        .replace(/[*_`#>|]/g, '').replace(/\s+/g, ' ').trim().slice(0, 600);
      if (!clean) return;
      this.stopSpeaking();
      if (this.o.serverTTS()) {
        try {
          const res = await fetch(this.o.base + '/api/assistant/voice/speak', { method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: clean, language: lang }) });
          if (res.status === 200) {
            const url = URL.createObjectURL(await res.blob());
            this.audio = new Audio(url);
            await new Promise(done => { this.audio.onended = done; this.audio.onerror = done; this.audio.play().catch(done); });
            URL.revokeObjectURL(url);
            return;
          }
        } catch (e) { /* fall back to the browser voice */ }
      }
      if (!('speechSynthesis' in global)) return;
      await new Promise(done => {
        const u = new SpeechSynthesisUtterance(clean), loc = LOCALES[lang] || 'en-IN', voices = speechSynthesis.getVoices();
        u.lang = loc;
        const v = voices.find(x => x.lang === loc) || voices.find(x => x.lang && x.lang.startsWith(loc.split('-')[0]));
        if (v) u.voice = v;
        u.onend = done; u.onerror = done;
        speechSynthesis.speak(u);
      });
    }

    stopSpeaking() {
      if (this.audio) { this.audio.pause(); this.audio = null; }
      if ('speechSynthesis' in global) speechSynthesis.cancel();
    }
  }
  Voice.LOCALES = LOCALES;
  global.SMVoice = Voice;
})(window);
