"""
Voice: speech-to-text and text-to-speech, tuned for Indian languages and names.

What changed from the original:
- The language is no longer forced to English. Hindi speech was being decoded as English,
  which is why names came out garbled. 'auto' lets the model detect the language; a chosen
  language is passed through when the model supports it.
- A vocabulary prompt (art forms, honorifics and the artist / institution names relevant to
  the current conversation) biases recognition toward the right spellings.
- Newer transcription models are tried first, with whisper-1 as the fallback.
- The openai package is imported lazily, so the rest of the app runs without it.
"""
import io
import logging
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Languages the OpenAI transcription models accept as a hint. Others (e.g. Odia) are
# transcribed with automatic detection instead of failing.
STT_LANGS = {'hi', 'en', 'mr', 'ta', 'te', 'bn', 'gu', 'kn', 'ml', 'pa', 'ur', 'as', 'ne'}
BROWSER_LOCALES = {'hi': 'hi-IN', 'en': 'en-IN', 'hinglish': 'en-IN', 'mr': 'mr-IN', 'ta': 'ta-IN',
                   'te': 'te-IN', 'bn': 'bn-IN', 'gu': 'gu-IN', 'kn': 'kn-IN', 'ml': 'ml-IN',
                   'pa': 'pa-IN', 'or': 'or-IN', 'as': 'as-IN', 'ur': 'ur-IN', 'auto': 'en-IN'}

GLOSSARY = ("SPIC MACAY, APR, Artist Payment Request, Virasat, Mini Virasat, Baithak, Lecture "
            "Demonstration, workshop, circuit, Pt., Ustad, Vidushi, Vidwan, Guru, sitar, sarod, sarangi, "
            "santoor, shehnai, bansuri, tabla, pakhawaj, mridangam, ghatam, veena, violin, harmonium, "
            "dhrupad, khayal, thumri, Carnatic, Hindustani, Bharatanatyam, Kathak, Odissi, Kuchipudi, "
            "Mohiniyattam, Manipuri, Sattriya, Kathakali, Kendriya Vidyalaya, Jawahar Navodaya Vidyalaya, "
            "IIT, NIT, DPS")


def build_vocabulary_prompt(language, names=None, institutions=None) -> str:
    """Context text for the transcription model. Written as natural sentences in the
    expected script, because the model treats the prompt as 'the text that came before'."""
    people = ', '.join([n for n in (names or []) if n][:20])
    places = ', '.join([i for i in (institutions or []) if i][:8])
    if language == 'hi':
        text = 'स्पिक मैके कार्यक्रम का पंजीकरण। '
        text += f'कलाकार: {people}। ' if people else ''
        text += f'संस्थान: {places}। ' if places else ''
        text += 'पंडित, उस्ताद, विदुषी, सितार, तबला, सरोद, संतूर, भरतनाट्यम, कथक, ओडिसी, लेक्चर डेमोंस्ट्रेशन, कॉन्सर्ट, विरासत।'
    elif language == 'hinglish':
        text = 'SPIC MACAY ka program register karna hai. '
        text += f'Artist {people} hain. ' if people else ''
        text += f'Institution {places}. ' if places else ''
        text += 'Kal shaam 6 baje IIT Bombay mein sitar concert hai, tabla par sangat hogi.'
    else:
        text = 'SPIC MACAY program registration. '
        text += f'Artists: {people}. ' if people else ''
        text += f'Institutions: {places}. ' if places else ''
        text += GLOSSARY + '.'
    return text[:900]


class VoiceService:
    def __init__(self, api_key: str, settings=None):
        self.api_key = api_key or ''
        self.settings = settings or (lambda key, default=None: default)
        self._client = None
        self.temp_dir = Path(tempfile.gettempdir()) / 'spicmacay_voice'
        self.temp_dir.mkdir(exist_ok=True)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _cli(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def transcribe(self, audio_bytes: bytes, filename: str = 'speech.webm', language=None,
                   prompt: str = None, model: str = None) -> dict:
        if not self.available:
            return {'success': False, 'text': '', 'error': 'Voice transcription is not configured (OPENAI_API_KEY).'}
        lang = (language or '').lower() or None
        api_lang = lang if lang in STT_LANGS else None
        models = [model or self.settings('voice.stt_model', 'gpt-4o-mini-transcribe'), 'whisper-1']
        last_err = None
        for m in dict.fromkeys(models):
            try:
                buf = io.BytesIO(audio_bytes)
                buf.name = filename
                kwargs = {'model': m, 'file': buf}
                if api_lang:
                    kwargs['language'] = api_lang
                if prompt:
                    kwargs['prompt'] = prompt
                r = self._cli().audio.transcriptions.create(**kwargs)
                return {'success': True, 'text': (getattr(r, 'text', '') or '').strip(),
                        'language': lang or 'auto', 'model': m}
            except Exception as e:  # try the next model
                last_err = e
                logger.warning('Transcription with %s failed: %s', m, e)
        return {'success': False, 'text': '', 'error': str(last_err)}

    def synthesize(self, text: str, voice: str = None, model: str = None, language: str = None) -> bytes:
        if not self.available or not text:
            return b''
        voice = voice or self.settings('voice.tts_voice', 'coral')
        instructions = ('Speak warmly and clearly at a calm pace, like a helpful coordinator at an '
                        'Indian classical music festival. Pronounce Indian names carefully.')
        if language == 'hi':
            instructions += ' Speak in natural Hindi.'
        for m in dict.fromkeys([model or self.settings('voice.tts_model', 'gpt-4o-mini-tts'), 'tts-1']):
            try:
                kwargs = {'model': m, 'voice': voice if m != 'tts-1' or voice in
                          ('alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer') else 'nova', 'input': text[:4000]}
                if m.startswith('gpt-4o'):
                    kwargs['instructions'] = instructions
                r = self._cli().audio.speech.create(**kwargs)
                return r.read() if hasattr(r, 'read') else getattr(r, 'content', b'')
            except Exception as e:
                logger.warning('Speech synthesis with %s failed: %s', m, e)
        return b''

    # ── Legacy API used by app/routes/voice_routes.py ─────────────────────────
    def transcribe_audio(self, audio_file_path: str, language: str = None) -> dict:
        with open(audio_file_path, 'rb') as fh:
            return self.transcribe(fh.read(), Path(audio_file_path).name, language,
                                   prompt=build_vocabulary_prompt(language))

    def text_to_speech(self, text: str, voice: str = 'nova', speed: float = 1.0) -> dict:
        audio = self.synthesize(text, voice=voice)
        if not audio:
            return {'success': False, 'error': 'Speech synthesis failed', 'audio_path': None}
        name = f'tts_{int(time.time() * 1000)}.mp3'
        path = self.temp_dir / name
        path.write_bytes(audio)
        return {'success': True, 'audio_path': str(path), 'audio_filename': name, 'voice': voice,
                'duration': len(text) / 15}

    def cleanup_old_files(self, max_age_hours: int = 24):
        cutoff = time.time() - max_age_hours * 3600
        for fp in self.temp_dir.glob('*.mp3'):
            try:
                if fp.stat().st_mtime < cutoff:
                    fp.unlink()
            except OSError:
                pass
