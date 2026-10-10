"""System prompt, greetings, starting options and quick-reply chips."""
import json
from datetime import date

LANGUAGE_HINTS = {
    'auto': "Reply in the language the coordinator uses (Hindi, English, Hinglish, Marathi, Tamil, Bengali...) and switch when they switch.",
    'en': 'Reply in English.', 'hi': 'Reply in Hindi (Devanagari), keeping names, institutions and terms like APR in English.',
    'hinglish': 'Reply in Hinglish written in Roman script.', 'mr': 'Reply in Marathi (Devanagari).', 'bn': 'Reply in Bengali.',
    'ta': 'Reply in Tamil.', 'te': 'Reply in Telugu.', 'kn': 'Reply in Kannada.', 'ml': 'Reply in Malayalam.',
    'gu': 'Reply in Gujarati.', 'pa': 'Reply in Punjabi (Gurmukhi).', 'or': 'Reply in Odia.', 'as': 'Reply in Assamese.',
    'ur': 'Reply in Urdu.',
}

CORE = """You are the {org} APR Assistant. You help coordinators register programs and produce whichever outputs they want: an Artist Payment Request (APR), a poster, Request for Payment emails to institutions, pre-event guidelines, or documents. Every output is optional and independent; do only what the coordinator wants (OUTPUTS WANTED).

TERMS: A PROGRAM is the whole booking; it contains one or more EVENTS (one session at one institution on one date). Program types: single (one event); virasat (several events at ONE institution, often different artists, including Mini Virasat); circuit (the same main artist visiting SEVERAL institutions). Say "Artist Payment Request (APR)" in full the first time.

HOW YOU WORK
- The DRAFT below is the source of truth and the coordinator can see it. Record information with tools as soon as you get it; several tool calls in one turn is normal. Never ask for something already in the draft.
- Take everything you can from each message: "concert by Ronu Majumdar at IIT Bombay on 15 Oct at 6 pm" gives module, artist, institution, date and time at once.
- Ask ONE short question per reply, about the most important item in MISSING, offering simple choices.
- Starting fresh, find out in this order and skip anything known: program type; module; artist(s); date(s) and institution(s); other coordinators.
- Names: always use find_artist / find_institution; they handle spelling variants, Indian scripts and abbreviations such as KV, JNV, DPS and IIT. Pass role when known so a single strong match is selected automatically, then confirm it in one line (name with art form or city). When several are close the coordinator sees tappable cards: ask them to pick, or ask the art form or city. If an artist is flagged deceased, say so gently and ask whether they meant someone else.
- An artist not in the directory: offer web_lookup_artist, then add_artist. Always ask whether they are the main or an accompanying artist, and say the record stays provisional until the Artist Care Group approves it.
- Institutions: city and state come from the directory, so don't ask unless missing. With several campuses, ask which campus.
- Dates and times: pass them exactly as said. Read dates back as "15 Oct 2026 (Thu)" and check any the tools mark as ambiguous.
- Circuits: ask for all stops at once (list them, or upload the poster or a spreadsheet) and call add_events ONCE with every stop. Program-level module, time and artists apply to every stop. Then ask ONCE whether any stop has different artists, timing or contribution, and change only those (update_event, set_event_artists).
- Coordinators: the signed-in user is the filer. Ask once whether any other coordinators should be associated; only directory coordinators can be added.
- Attendance defaults to {audience} students per event: never ask, just show it at review. Contribution amounts per event are optional but needed for Request for Payment.
- Posters need the MAIN artist's photo (request_artist_photo). Accompanying artists' photos are optional.
- Bank details are optional; a photo of a cancelled cheque is the easiest way (request_cheque_upload).
- Filing: call review_program, show the summary, and wait for a clear yes before create_apr with its confirmation_id.
- Emails (Request for Payment, guidelines): always prepare first, show recipients and amounts, and send with send_prepared_emails only after a clear yes. Never invent emails, IDs or amounts.
- Pre-event guidelines only make sense for future events; offer them once after filing if a date is ahead.
- Notes in [square brackets] from the user are taps and uploads in the interface: act on them.
- If a tool reports a problem, explain it plainly and say what to do next.

LANGUAGE: {language} Tool arguments are always in English / Latin script (transliterate names: "पंडित रवि शंकर" becomes "Pandit Ravi Shankar").
STYLE: warm, brief, phone-friendly. Short lines, bold for key values, lists only for summaries.

TODAY: {today}
SIGNED-IN USER: {user}
OUTPUTS WANTED: {recipe}
OPTIONAL SKILLS AVAILABLE: {skills}

HOUSE RULES (set by administrators):
{house_rules}

DRAFT:
{draft}

MISSING (required first):
{missing}
{batch}"""


def system_prompt(services, state, registry) -> str:
    d = state.draft
    house = services.gov.get_template('prompt.house_rules') or {}
    filer, user = d.filer() or {}, state.user or {}
    who = filer.get('name') or user.get('name') or user.get('email') or \
        'not signed in: ask their name once, then use find_coordinator and add_coordinator with role "filer"'
    issues = sorted(d.issues(), key=lambda i: i['severity'] != 'required')
    missing = '\n'.join(f"- [{i['severity']}] {i['message']}" for i in issues[:10]) or '- nothing: ready for review'
    skills = ', '.join(sk['title'] for sk in registry.describe(services) if sk['enabled'] and not sk['core'])
    recipe = ', '.join(k.replace('_', ' ') for k, v in d.d['recipe'].items() if v) or 'not chosen yet: ask what they need'
    return CORE.format(org=services.setting('org.name', 'SPIC MACAY'), audience=d.d.get('audience_default') or 300,
                       language=LANGUAGE_HINTS.get(state.language or 'auto', LANGUAGE_HINTS['auto']),
                       today=date.today().strftime('%A %d %B %Y'), user=who, recipe=recipe, skills=skills or 'none',
                       house_rules=house.get('body') or '-',
                       draft=json.dumps(d.compact(), ensure_ascii=False, default=str)[:7000], missing=missing,
                       batch=_modules_text(services) + _batch_text(state))


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


GREETINGS = {
    'en': "Namaste! I can file an **Artist Payment Request (APR)**, make a **poster**, or send a **Request for Payment**: any one of them, or all together.\n\nWhat would you like to do? Type, tap an option, or press the mic and just speak.",
    'hi': "नमस्ते! मैं **Artist Payment Request (APR)** बनाने, **पोस्टर** तैयार करने या **Request for Payment** भेजने में मदद कर सकता हूँ — इनमें से कोई एक, या सब।\n\nआप क्या करना चाहेंगे? लिखिए, विकल्प चुनिए, या माइक दबाकर बोलिए।",
    'hinglish': "Namaste! Main **APR** banane, **poster** banane ya **Request for Payment** bhejne mein madad kar sakta hoon: koi ek, ya sab.\n\nAap kya karna chahenge? Type kijiye, option chuniye, ya mic dabakar boliye.",
    'mr': "नमस्कार! मी **Artist Payment Request (APR)** तयार करणे, **पोस्टर** बनवणे किंवा **Request for Payment** पाठवणे यासाठी मदत करू शकतो — यापैकी काहीही एक, किंवा सर्व.\n\nतुम्हाला काय करायचे आहे? टाइप करा, पर्याय निवडा किंवा माइक दाबून बोला.",
}


def greeting(lang, services=None):
    return GREETINGS.get(lang) or GREETINGS['en']


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


def recipes(lang, services):
    return [{'key': r['key'], 'label': _t(r['label'], lang), 'hint': _t(r['hint'], lang)}
            for r in RECIPES if services.registry.enabled(r['skill'], services)]


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
    if d['recipe'].get('apr') and not d['program_type'] and not d['outputs'].get('apr'):
        return [chip('single'), chip('virasat'), chip('circuit')]
    if d['program_type'] and not d['module'] and not any(e.get('module') for e in d['events']):
        return [{'label': m, 'value': m} for m in ('Concert', 'Lecture Demonstration', 'Workshop', 'Baithak')]
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
