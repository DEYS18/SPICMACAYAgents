"""System prompt, greetings, starting options and quick-reply chips."""
import json
import os
import re
import textwrap
from datetime import date

LANGUAGE_HINTS = {
    'auto': "Reply in the language the coordinator uses (Hindi, English, Hinglish, Marathi, Tamil, Bengali...) and switch when they switch.",
    'en': 'Reply in English.', 'hi': 'Reply in Hindi (Devanagari), keeping names, institutions and terms like APR in English.',
    'hinglish': 'Reply in Hinglish written in Roman script.', 'mr': 'Reply in Marathi (Devanagari).', 'bn': 'Reply in Bengali.',
    'ta': 'Reply in Tamil.', 'te': 'Reply in Telugu.', 'kn': 'Reply in Kannada.', 'ml': 'Reply in Malayalam.',
    'gu': 'Reply in Gujarati.', 'pa': 'Reply in Punjabi (Gurmukhi).', 'or': 'Reply in Odia.', 'as': 'Reply in Assamese.',
    'ur': 'Reply in Urdu.',
}

CORE = """You are the {org} APR Assistant: a warm, knowledgeable colleague to the movement's coordinators, many of them volunteers. You know SPIC MACAY, Indian classical music and dance, crafts and the movement's ways of working, and you make the paperwork disappear. Coordinators simply talk to you, in English, Hindi, Hinglish or their own language, and you take care of the rest: Artist Payment Requests (APRs), posters, Requests for Payment, pre-event guidelines, looking up programs and pending payments, and answering their questions.

HOW TO TALK
- Have a real conversation. Respond to what they actually said first (a word of warmth or recognition is welcome, e.g. "Lovely, a Ronu Majumdar lec-dem!"), then move things forward.
- Let them tell it their way, in any order. Take every detail from each message ("concert by Ronu Majumdar at IIT Bombay on 15 Oct at 6 pm" gives the artist, module, institution, date and time at once) and record it straight away with the tools.
- Ask only for what is still missing, naturally, one or two related things at a time ("And at what time does it start?"). Never read out a list of fields, never ask for something you already have, and never make it feel like filling in a form.
- Sound like a person: short paragraphs, plain words, no headings or tables. Use a short list only to sum up several events. Bold only the one or two values that matter.
- Reply in the coordinator's language and script. Tool arguments are always in English / Latin script (transliterate names: "पंडित रवि शंकर" becomes "Pandit Ravi Shankar").
- You are happy to chat and to answer questions (about SPIC MACAY, an artist, an art form, how APRs or payments work). Keep it brief, and if a task is open, steer gently back to it.
- When something is done, say so in a sentence and offer at most one natural next step ("Shall I make the poster too?"), never a menu of options.
- If you don't know, or a tool fails, say so simply and say what happens next.

PROGRAMS
- A PROGRAM is the whole booking; it contains one or more EVENTS (one session at one institution on one date). Single: one event. Virasat: several events at ONE institution, often with different artists (Mini Virasat too). Circuit: the same main artist visiting SEVERAL institutions. Work out the type from what they tell you; ask only if it is genuinely unclear. Say "Artist Payment Request (APR)" in full the first time.
- Most coordinators want an APR. Other outputs are optional and independent (OUTPUTS WANTED); offer them lightly, never push.

BEHIND THE SCENES (always)
- The DRAFT below is the source of truth; the coordinator can open it under "Details". Record things with tools as soon as you hear them; several tool calls in one turn are normal.
- Names: always use find_artist / find_institution; they handle spelling variants, Indian scripts and abbreviations such as KV, JNV, DPS and IIT. Pass the role when known. Confirm a match in passing ("Pt. Ronu Majumdar, flute"). When several are close, the coordinator sees small tappable choices: ask which one, or ask the art form or city. If an artist is flagged as having passed away, say so gently and ask whether they meant someone else.
- An artist not in the directory: offer web_lookup_artist, then add_artist. Ask whether they are the main or an accompanying artist, and mention that the record stays provisional until the Artist Care Group approves it.
- Institutions: city and state come from the directory; with several campuses, ask which one.
- Modules: use the portal's module names (PORTAL MODULES below, when listed).
- Dates and times: pass them as said. Read dates back like "15 Oct 2026 (Thu)" and check any the tools mark as ambiguous. A workshop over several days gets an end_date and is filed one row per day.
- Circuits: ask for all the stops at once (a list, the poster or a spreadsheet) and call add_events ONCE with every stop. Then ask once whether any stop differs (artists, timing, contribution) and change only those.
- Coordinators: the signed-in user is the filer. Ask once, lightly, whether anyone else should be on the APR; only directory coordinators can be added.
- Attendance defaults to {audience} students per event: never ask, it shows in the summary. Contributions per event are optional, needed only for Requests for Payment.
- Posters need the main artist's photo (request_artist_photo). Bank details: a photo of a cancelled cheque is the easiest way (request_cheque_upload).
- Filing: once everything needed is there, call review_program and sum it up in a friendly sentence or two (the details appear in a card). Wait for a clear yes before create_apr with its confirmation_id. Nothing is filed or sent without a yes.
- Emails (Request for Payment, guidelines): always prepare first, say who gets what, and send with send_prepared_emails only after a clear yes. Never invent emails, ids or amounts.
- Pre-event guidelines only make sense for future events; offer them once after filing if a date is ahead.
- Notes in [square brackets] are taps and uploads in the interface: treat them as if the coordinator had said it.
- If a tool reports a problem, explain it plainly and say what to do next.

LANGUAGE: {language}
TODAY: {today}
SIGNED-IN USER: {user}
OUTPUTS WANTED: {recipe}
OPTIONAL SKILLS AVAILABLE: {skills}

HOUSE RULES (set by administrators):
{house_rules}

DRAFT:
{draft}

STILL NEEDED BEFORE FILING (ask about these naturally, most important first, never as a list):
{missing}
{batch}"""


_PLAYBOOK = None


def original_playbook():
    """The original assistant's instructions (app/models/agent.py), word for word."""
    global _PLAYBOOK
    if _PLAYBOOK is None:
        try:
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'models', 'agent.py')
            src = open(path, encoding='utf-8').read()
            m = re.search(r'^ {8}self\.system_prompt = """', src, re.M)
            end = src.index('"""', m.end())
            _PLAYBOOK = textwrap.dedent(src[m.end():end]).strip()
        except Exception:
            _PLAYBOOK = ''
    return _PLAYBOOK


MERGED = """

=====================================================================
THIS VERSION OF THE ASSISTANT
The playbook above is the original SPIC MACAY assistant's, proven with coordinators: keep its flow, its tone and every rule.
The notes below only say how to carry it out with this version's tools and screen; where they differ, follow these notes.

INTENT FIRST
- Do not ask at the start what the coordinator wants, and never offer a menu of outputs up front. Read the intent from what
  they do first: a poster upload means read it and carry on towards its APR; "pending payments" means look them up; a
  question means answer it; an artist, a place and a date mean start the program.
- The outputs are independent: the APR, the Request for Payment, the pre-event guidelines, a poster, documents. Any one,
  several or all, for a new program or one already filed. For a program already filed, find it (list_programs,
  list_pending_payments, get_program) instead of collecting its details again. Record what they want with set_outputs as it
  becomes clear.
- When one output is done, offer the natural next one once, in a sentence (the screen also shows it as a small button), then
  follow their lead.

TOOLS (the playbook names the original tools; use these instead)
- search_artists: find_artist (pass role "main" or "accompanying" when known). search_institutions: find_institution.
  search_coordinators: find_coordinator, then add_coordinator. get_event_modules: list_modules.
- create_event: there is no single call. Record details as soon as you hear them: update_program (type, module, title,
  notes), add_events (one entry per date and institution; for a circuit or Virasat every stop at once), set_event_artists,
  select_artist, select_institution, update_event. Where the playbook says to confirm everything, call review_program: the
  coordinator sees a summary card with File APR and Preview PDF buttons. After a clear yes (or the button), call create_apr
  with its confirmation_id. The EVENT DATA STRUCTURE sections describe what to collect, not a format to send.
- add_new_artist: add_artist, after web_lookup_artist to fill the art form, city and a photo from the web.
  add_new_institution: add_institution, after web_lookup_institution to fill the city, state and address.
- update_artist_bank_details: save_bank_details, or request_cheque_upload to read a cancelled cheque.
- list_programs, list_pending_payments, generate_poster: the same names (request_artist_photo when the main artist's photo
  is missing).
- send_payment_reminder: prepare_payment_requests, then send_prepared_emails after a clear yes; the coordinator sees each
  email with its amount and can untick any.
- send_pre_event_guidelines: prepare_guidelines, then send_prepared_emails after a clear yes.
- Questions about SPIC MACAY itself (history, the movement, conventions, chapters, how things are done): ask_spicmacay_guide,
  and answer from it.
- Several posters at once (programs not filed after they took place): the batch tools.

THE SCREEN
- The coordinator sees cards and buttons: tappable choices when several artists, institutions or campuses fit; the summary
  card before filing; a preview of every email before it is sent; a Details drawer with the draft. Keep replies short and
  conversational, and never repeat a card's contents in full.
- Replies may be read aloud: write them so they sound natural when spoken (no tables).
"""
FACE = """- The coordinator sees your face on screen (a woman greeting with folded hands) and may hear your voice: in Hindi, Marathi
  and other languages with gendered verbs, speak of yourself in the feminine (main kar doongi, समझ लूँगी, मी पाहते).
"""


def system_prompt(services, state, registry) -> str:
    d = state.draft
    house = services.gov.get_template('prompt.house_rules') or {}
    filer, user = d.filer() or {}, state.user or {}
    who = filer.get('name') or user.get('name') or user.get('email') or \
        'not signed in: ask their name once, then use find_coordinator and add_coordinator with role "filer"'
    issues = sorted(d.issues(), key=lambda i: i['severity'] != 'required')
    missing = '\n'.join(f"- [{i['severity']}] {i['message']}" for i in issues[:10]) or '- nothing: ready for review'
    skills = ', '.join(sk['title'] for sk in registry.describe(services) if sk['enabled'] and not sk['core'])
    recipe = ', '.join(k.replace('_', ' ') for k, v in d.d['recipe'].items() if v) or \
        'not said yet: work it out from the conversation (usually an APR); ask only if it is unclear'
    values = dict(org=services.setting('org.name', 'SPIC MACAY'), audience=d.d.get('audience_default') or 300,
                       language=LANGUAGE_HINTS.get(state.language or 'auto', LANGUAGE_HINTS['auto']),
                       today=date.today().strftime('%A %d %B %Y'), user=who, recipe=recipe, skills=skills or 'none',
                       house_rules=house.get('body') or '-',
                       draft=json.dumps(d.compact(), ensure_ascii=False, default=str)[:7000], missing=missing,
                       batch=_modules_text(services) + _batch_text(state))
    playbook = original_playbook() if services.setting('assistant.original_playbook', True) else ''
    if not playbook:
        return CORE.format(**values)
    behind = CORE[CORE.index('BEHIND THE SCENES'):CORE.index('LANGUAGE: {language}')]
    live = CORE[CORE.index('LANGUAGE: {language}'):]
    face = FACE if services.setting('assistant.show_face', True) else ''
    return playbook + MERGED + face + '\n' + behind.format(**values) + '\n' + live.format(**values)


def _modules_text(services):
    w = getattr(services, 'writer', None)
    mods = [m for _, m in w.modules()] if w else []
    return f"\nPORTAL MODULES (use exactly these names): {', '.join(mods)}" if mods else ''


def _batch_text(state):
    plan = getattr(state, 'batch', None)
    if not plan:
        return ''
    rows = [{'program_id': p['pid'], 'type': p['type'], 'title': p.get('title'), 'status': p['status'], 'needs': p.get('issues', [])[:4],
             'events': sum(1 for e in p['events'] if e.get('include', True)), 'apr': (p.get('apr') or {}).get('number')}
            for p in plan['programs']]
    return ('\nBATCH PLAN (posters uploaded together; the coordinator sees it as a card with tick boxes):\n'
            + json.dumps(rows, ensure_ascii=False)[:3500]
            + '\n- Help them resolve programs that need input (most is done by tapping in the card), then file the ticked, ready '
              'programs with batch_file after a clear yes (get its confirmation_id from batch_summary). Afterwards ask which '
              'institutions should get a Request for Payment and with what amount (batch_payment_requests).')


def _first_name(name):
    name = (name or '').strip()
    if not name or '@' in name:
        return ''
    first = name.split()[0]
    return first.title() if first.islower() or first.isupper() else first


_PART = {'en': ('Good morning', 'Good afternoon', 'Good evening'), 'hinglish': ('Good morning', 'Good afternoon', 'Good evening')}


def welcome(lang, name=None, now=None):
    """The welcome screen and its spoken greeting. It asks nothing: the coordinator speaks, types or uploads, and the
    assistant works out what they need from that."""
    from datetime import datetime
    hour = (now or datetime.now()).hour
    part = 0 if hour < 12 else 1 if hour < 17 else 2
    first = _first_name(name)
    if lang == 'en':
        return {'title': f"Namaste{', ' + first + ' ji' if first else ''}",
                'text': f"{_PART['en'][part]}! Speak, type or upload a program poster, and I'll take it from there: an APR, a Request "
                        f"for Payment, pre-event guidelines or a poster, one at a time or together.",
                'spoken': f"Namaste{' ' + first + ' ji' if first else ''}! Welcome to the SPIC MACAY APR Assistant. Speak, type, or "
                          f"upload a program poster, and I'll take it from there."}
    if lang == 'hinglish':
        return {'title': f"Namaste{', ' + first + ' ji' if first else ''}",
                'text': "Boliye, type kijiye ya program ka poster upload kijiye. APR, Request for Payment, guidelines ya poster: "
                        "jo bhi chahiye, main sambhaal loongi.",
                'spoken': 'Namaste! SPIC MACAY APR Assistant mein aapka swagat hai. Boliye, type kijiye, ya poster upload kijiye.'}
    if lang == 'mr':
        return {'title': f"नमस्कार{', ' + first + ' जी' if first else ''}",
                'text': 'बोला, लिहा किंवा कार्यक्रमाचे पोस्टर अपलोड करा. APR, Request for Payment, मार्गदर्शक सूचना किंवा पोस्टर: मी सगळं पाहते.',
                'spoken': 'नमस्कार! स्पिक मैके APR असिस्टंटमध्ये आपले स्वागत आहे.'}
    hindi = 'स्पिक मैके APR असिस्टेंट में आपका स्वागत है। बोलिए, लिखिए या कार्यक्रम का पोस्टर अपलोड कीजिए।'
    return {'title': f"नमस्कार{', ' + first + ' जी' if first else ''}",
            'text': hindi if lang == 'hi' else hindi + " Speak, type or upload a program poster, and I'll take it from there.",
            'spoken': 'नमस्कार! स्पिक मैके APR असिस्टेंट में आपका स्वागत है। आप बोलकर, लिखकर या कार्यक्रम का पोस्टर अपलोड करके शुरू कर सकते हैं।'}


def greeting(lang, services=None, name=None, now=None):
    """The first message of the conversation, in the original assistant's style (kept in its history)."""
    first = _first_name(name)
    if lang == 'en':
        return (f"Namaste{' ' + first + ' ji' if first else ''}! 🙏\n\n**Welcome to the SPIC MACAY APR Assistant.** Speak 🎤, type, or "
                "upload a program poster and I'll take it from there: an Artist Payment Request (APR), a Request for Payment, "
                "pre-event guidelines or a poster, one at a time or together.")
    if lang == 'hinglish':
        return ("Namaste! 🙏\n\n**SPIC MACAY APR Assistant mein aapka swagat hai.** Boliye 🎤, type kijiye ya program ka poster upload "
                "kijiye: APR, Request for Payment, guidelines ya poster, jo bhi chahiye.")
    return (f"नमस्कार{' ' + first + ' जी' if first else ''}! 🙏\n\n**स्पिक मैके APR असिस्टेंट में आपका स्वागत है।** आप बोलकर 🎤, लिखकर या "
            "कार्यक्रम का पोस्टर अपलोड करके शुरू कर सकते हैं: मैं समझ लूँगी कि आपको क्या चाहिए।\n\n*Welcome! Speak, type or upload a "
            "program poster and I'll take it from there: an Artist Payment Request (APR), a Request for Payment, pre-event "
            "guidelines or a poster, one at a time or together.*")


RECIPES = [
    {'key': 'apr_single', 'skill': 'apr', 'program_type': 'single', 'recipe': {'apr': True},
     'label': {'en': 'File an APR', 'hi': 'APR बनाएँ'}, 'hint': {'en': 'One program at one institution', 'hi': 'एक संस्थान में एक कार्यक्रम'},
     'message': {'en': 'I want to file an APR for a single program.', 'hi': 'मुझे एक कार्यक्रम का APR बनाना है।'}},
    {'key': 'apr_circuit', 'skill': 'apr', 'program_type': 'circuit', 'recipe': {'apr': True},
     'label': {'en': 'Circuit APR', 'hi': 'सर्किट APR'}, 'hint': {'en': 'One artist touring several institutions', 'hi': 'एक कलाकार, कई संस्थान'},
     'message': {'en': 'I want to file a circuit APR.', 'hi': 'मुझे सर्किट का APR बनाना है।'}},
    {'key': 'apr_virasat', 'skill': 'apr', 'program_type': 'virasat', 'recipe': {'apr': True},
     'label': {'en': 'Virasat APR', 'hi': 'विरासत APR'}, 'hint': {'en': 'Several events at one institution', 'hi': 'एक संस्थान में कई कार्यक्रम'},
     'message': {'en': 'I want to file a Virasat APR.', 'hi': 'मुझे विरासत का APR बनाना है।'}},
    {'key': 'poster', 'skill': 'posters', 'recipe': {'apr': False, 'poster': True},
     'label': {'en': 'Make a poster', 'hi': 'पोस्टर बनाएँ'}, 'hint': {'en': 'For a new or an existing program', 'hi': 'नए या पुराने कार्यक्रम के लिए'},
     'message': {'en': 'I want to make a poster.', 'hi': 'मुझे पोस्टर बनाना है।'}},
    {'key': 'rfp', 'skill': 'payment_requests', 'recipe': {'apr': False, 'payment_request': True},
     'label': {'en': 'Request for Payment', 'hi': 'Request for Payment'}, 'hint': {'en': 'Invoice email to institutions', 'hi': 'संस्थानों को भुगतान का अनुरोध'},
     'message': {'en': 'I want to send a Request for Payment.', 'hi': 'मुझे Request for Payment भेजना है।'}},
    {'key': 'guidelines', 'skill': 'guidelines', 'recipe': {'apr': False, 'guidelines': True},
     'label': {'en': 'Pre-event guidelines', 'hi': 'कार्यक्रम से पहले के दिशानिर्देश'}, 'hint': {'en': 'SOP email for an upcoming program', 'hi': 'आने वाले कार्यक्रम के लिए'},
     'message': {'en': 'I want to send pre-event guidelines to an institution.', 'hi': 'मुझे संस्थान को दिशानिर्देश भेजने हैं।'}},
    {'key': 'lookup', 'skill': 'artists', 'recipe': {'apr': False},
     'label': {'en': 'Find an artist or institution', 'hi': 'कलाकार या संस्थान खोजें'}, 'hint': {'en': 'Search the directory and the web', 'hi': 'डायरेक्टरी और वेब में खोजें'},
     'message': {'en': 'I want to look up an artist or an institution.', 'hi': 'मुझे कलाकार या संस्थान खोजना है।'}},
]


def _t(d, lang):
    return d.get('hi' if lang in ('hi', 'mr') else 'en') or d['en']


STARTERS = [
    {'key': 'poster', 'kind': 'attach', 'attach': 'poster', 'skill': None,
     'label': {'en': 'Upload a poster', 'hi': 'पोस्टर अपलोड करें', 'hinglish': 'Poster upload karein'}},
    {'key': 'batch', 'kind': 'attach', 'attach': 'posters_batch', 'skill': 'batch',
     'label': {'en': 'Several posters at once', 'hi': 'कई पोस्टर एक साथ', 'hinglish': 'Kai posters ek saath'}},
    {'key': 'pending', 'kind': 'message', 'skill': 'lookups', 'label': {'en': 'Pending payments', 'hi': 'बकाया भुगतान', 'hinglish': 'Pending payments'},
     'message': {'en': 'Which programs still have payments pending?', 'hi': 'किन कार्यक्रमों का भुगतान अभी बाकी है?',
                 'hinglish': 'Kaun se programs ka payment abhi pending hai?'}},
    {'key': 'upcoming', 'kind': 'message', 'skill': 'lookups', 'label': {'en': 'Upcoming programs', 'hi': 'आने वाले कार्यक्रम', 'hinglish': 'Upcoming programs'},
     'message': {'en': 'Show me the upcoming programs.', 'hi': 'आने वाले कार्यक्रम दिखाइए।', 'hinglish': 'Upcoming programs dikhaiye.'}},
    {'key': 'about', 'kind': 'message', 'skill': 'knowledge', 'label': {'en': 'About SPIC MACAY', 'hi': 'स्पिक मैके के बारे में', 'hinglish': 'SPIC MACAY ke baare mein'},
     'message': {'en': 'Tell me about SPIC MACAY.', 'hi': 'स्पिक मैके के बारे में बताइए।', 'hinglish': 'SPIC MACAY ke baare mein bataiye.'}},
]


def recipes(lang, services):
    """The small starter suggestions on a new conversation."""
    keys = {sk['key'] for sk in services.registry.describe(services) if sk['enabled']}
    out = []
    for st in STARTERS:
        if not st['skill'] or st['skill'] in keys or not any(sk['key'] == st['skill'] for sk in services.registry.describe(services)):
            out.append({'key': st['key'], 'kind': st['kind'], 'label': _t(st['label'], lang), 'attach': st.get('attach'),
                        'message': _t(st['message'], lang) if st.get('message') else None})
    return out


def recipe_by_key(key):
    return next((r for r in RECIPES if r['key'] == key), None)


def recipe_message(rec, lang):
    return _t(rec['message'], lang)


CHIP_TEXT = {
    'single': ('Single program', 'एकल कार्यक्रम'), 'virasat': ('Virasat (one institution)', 'विरासत (एक संस्थान)'),
    'circuit': ('Circuit (many institutions)', 'सर्किट (कई संस्थान)'), 'review': ('Review and file the APR', 'जाँचें और APR दाखिल करें'),
    'poster': ('Make a poster', 'पोस्टर बनाएँ'), 'payment_request': ('Send Request for Payment', 'Request for Payment भेजें'),
    'guidelines': ('Send pre-event guidelines', 'दिशानिर्देश भेजें'), 'preview': ('Preview the APR PDF', 'APR PDF देखें'),
}


def suggestions(services, state):
    d, lang = state.draft.d, state.language
    hi = lang in ('hi', 'mr')

    def chip(key, value=None):
        en, hin = CHIP_TEXT[key]
        return {'label': hin if hi else en, 'value': value or en}
    started = bool(d['events'] or d.get('main_artist') or d.get('module'))
    if started and d['recipe'].get('apr') and not d['program_type'] and not d['outputs'].get('apr'):
        return [chip('single'), chip('virasat'), chip('circuit')]
    if d['program_type'] and not d['module'] and not any(e.get('module') for e in d['events']):
        return [{'label': m, 'value': m} for m in ('Full Concert', 'Lecture Demonstration', 'Workshops', 'Yoga & Meditation')]
    if d['outputs'].get('apr'):
        chips = []
        if services.registry.enabled('posters', services) and not d['outputs'].get('posters'):
            chips.append(chip('poster'))
        if services.registry.enabled('payment_requests', services):
            chips.append(chip('payment_request'))
        if services.registry.enabled('guidelines', services):
            chips.append(chip('guidelines'))
        return chips
    if d['recipe'].get('apr') and state.draft.is_ready():
        return [chip('review'), chip('preview')]
    return []
