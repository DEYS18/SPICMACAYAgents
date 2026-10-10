"""
Text normalisation for Indian names, institutions and voice transcripts.

Deterministic and dependency-free so it can be unit-tested. The directory search
(app/search/resolver.py) is built on these primitives; the language model is only asked
to arbitrate when these scores are genuinely ambiguous.
"""
import re
import unicodedata
from functools import lru_cache
from typing import List, Tuple

# ── Honorifics ────────────────────────────────────────────────────────────────
# Stripped from the start of a name only, so a first name that is also a title word
# ("Padma Talwalkar", "Guru Dutt") survives. "Padma" only counts before Shri/Bhushan.
LEADING_HONORIFICS = frozenset("""
pt pdt pandit pan ustad ustaad ust vidushi vidushee vid vidwan vidvan vidhushi dr do doctor
swami shri sri shree sree sushree smt shrimati srimati shreemati shreematee shrimathi kumari
kum guru prof professor begum mr mrs ms miss janab thiru tmt selvi acharya aacharya aachaarya
maestro sh kalaimamani padmashri padmasri padmabhushan padmavibhushan
""".split())
PADMA_FOLLOWERS = frozenset({'shri', 'sri', 'shree', 'bhushan', 'vibhushan', 'bhusan', 'vibhusan'})
TRAILING_HONORIFICS = frozenset({'ji', 'saheb', 'sahab', 'sahib', 'garu', 'avargal'})
DECEASED_MARKERS = frozenset({'late', 'swargiya', 'svargiya', 'swargeeya', 'svargeeya'})

# ── Indic scripts → Latin ─────────────────────────────────────────────────────
# Unicode lays out the major Indic blocks on the same grid as Devanagari, so Bengali,
# Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada and Malayalam letters are mapped onto
# their Devanagari twin first and then romanised with one table. Approximate, but names
# only need to land close enough for the phonetic matcher below.
_DEV_CONS = {
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'n', 'च': 'ch', 'छ': 'chh', 'ज': 'j',
    'झ': 'jh', 'ञ': 'n', 'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n', 'त': 't',
    'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n', 'ऩ': 'n', 'प': 'p', 'फ': 'ph', 'ब': 'b',
    'भ': 'bh', 'म': 'm', 'य': 'y', 'र': 'r', 'ऱ': 'r', 'ल': 'l', 'ळ': 'l', 'ऴ': 'zh',
    'व': 'v', 'श': 'sh', 'ष': 'sh', 'स': 's', 'ह': 'h',
    '\u0958': 'q', '\u0959': 'kh', '\u095a': 'g', '\u095b': 'z', '\u095c': 'r',
    '\u095d': 'rh', '\u095e': 'f', '\u095f': 'y',
}
_NUKTA = {'क': 'q', 'ख': 'kh', 'ग': 'g', 'ज': 'z', 'ड': 'r', 'ढ': 'rh', 'फ': 'f'}
_DEV_VOWEL = {'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo', 'ऋ': 'ri',
              'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'ऑ': 'o', 'ऍ': 'e', 'ऎ': 'e', 'ऒ': 'o'}
_DEV_MATRA = {'ा': 'aa', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo', 'ृ': 'ri', 'े': 'e',
              'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ॉ': 'o', 'ॅ': 'e', 'ॆ': 'e', 'ॊ': 'o'}
_DEV_SIGN = {'ं': 'n', 'ँ': 'n', 'ः': 'h', '्': '', '़': '', 'ऽ': '', '।': ' ', '॥': ' '}
_DEV_DIGIT = {chr(0x0966 + i): str(i) for i in range(10)}
_INDIC_RE = re.compile('[\u0900-\u0dff]')


def _to_devanagari(ch: str) -> str:
    code = ord(ch)
    if 0x0980 <= code <= 0x0DFF:
        return chr(0x0900 + (code - (code & ~0x7F)))
    return ch


def transliterate_indic(text: str) -> str:
    """Romanise Devanagari (and, via the shared grid, other Indic scripts)."""
    chars = [_to_devanagari(c) for c in text]
    out, i, n = [], 0, len(chars)
    while i < n:
        c = chars[i]
        if c in _DEV_CONS:
            base, j = _DEV_CONS[c], i + 1
            if j < n and chars[j] == '\u093c':
                base, j = _NUKTA.get(c, base), j + 1
            if j < n and chars[j] in _DEV_MATRA:
                out.append(base + _DEV_MATRA[chars[j]]); j += 1
            elif j < n and chars[j] == '\u094d':
                out.append(base); j += 1
            else:
                out.append(base + 'a')
            i = j
            continue
        out.append(_DEV_VOWEL.get(c) or _DEV_SIGN.get(c) or _DEV_DIGIT.get(c) or c)
        i += 1
    s = ''.join(out)
    return re.sub(r'(?<=[bcdfghjklmnpqrstvwxyz])a\b', '', s)   # word-final schwa


def to_latin(text: str) -> str:
    text = str(text or '')
    if _INDIC_RE.search(text):
        text = transliterate_indic(text)
    text = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in text if not unicodedata.combining(ch))


def latin1_safe(text, limit=None):
    """Text the portal's latin1 tables accept under MariaDB strict mode. MariaDB's latin1 is Windows-1252, so
    curly quotes and dashes are fine; Indian scripts are romanised (title case), accents dropped, the rupee
    sign written as Rs, and anything else that cannot be stored removed."""
    if text is None:
        return None
    s = str(text)
    try:
        s.encode('cp1252')
    except UnicodeEncodeError:
        s = s.replace('\u20b9', 'Rs ')
        s = re.sub('[\u0900-\u0dff][\u0900-\u0dff\u200c\u200d ]*', lambda m: transliterate_indic(m.group(0)).title() + ' ', s)
        out = []
        for ch in s:
            try:
                ch.encode('cp1252')
                out.append(ch)
            except UnicodeEncodeError:
                d = ''.join(c for c in unicodedata.normalize('NFKD', ch) if not unicodedata.combining(c))
                try:
                    d.encode('cp1252')
                    out.append(d)
                except UnicodeEncodeError:
                    pass
        s = re.sub(' {2,}', ' ', ''.join(out)).strip()
    return s[:limit] if limit else s


def normalize(text: str) -> str:
    s = to_latin(text).lower().replace('&', ' and ')
    s = re.sub(r"[\u2019'`\u00b4\u2018]", '', s)      # Xavier's -> xaviers
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


# ── Phonetic canonicalisation for Indian spellings ───────────────────────────
_CANON_RULES = (
    ('chh', 'ch'), ('ksh', 'ks'), ('sh', 's'), ('ph', 'f'), ('bh', 'b'), ('dh', 'd'),
    ('th', 't'), ('kh', 'k'), ('gh', 'g'), ('jh', 'j'), ('ck', 'k'), ('q', 'k'),
    ('x', 'ks'), ('z', 'j'), ('w', 'v'), ('oo', 'u'), ('ou', 'o'), ('au', 'o'),
    ('ee', 'i'), ('ii', 'i'), ('aa', 'a'), ('ey', 'e'), ('ai', 'e'), ('ay', 'e'),
    ('iya', 'ia'), ('yy', 'y'),
)


@lru_cache(maxsize=100000)
def canon(tok: str) -> str:
    t = tok
    for a, b in _CANON_RULES:
        t = t.replace(a, b)
    t = re.sub(r'(.)\1+', r'\1', t)
    if len(t) > 3 and t.endswith('h'):
        t = t[:-1]
    if len(t) > 4 and t.endswith('a'):
        t = t[:-1]
    return t


@lru_cache(maxsize=100000)
def skeleton(tok: str) -> str:
    c = canon(tok)
    return (c[0] + re.sub('[aeiouy]', '', c[1:])) if c else ''


@lru_cache(maxsize=300000)
def jaro_winkler(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    l1, l2 = len(s1), len(s2)
    if not l1 or not l2:
        return 0.0
    dist = max(max(l1, l2) // 2 - 1, 0)
    m1, m2, matches = [False] * l1, [False] * l2, 0
    for i in range(l1):
        for j in range(max(0, i - dist), min(i + dist + 1, l2)):
            if not m2[j] and s1[i] == s2[j]:
                m1[i] = m2[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    t, k = 0, 0
    for i in range(l1):
        if m1[i]:
            while not m2[k]:
                k += 1
            if s1[i] != s2[k]:
                t += 1
            k += 1
    jaro = (matches / l1 + matches / l2 + (matches - t / 2) / matches) / 3
    prefix = 0
    for a, b in zip(s1, s2):
        if a != b or prefix == 4:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


@lru_cache(maxsize=300000)
def token_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if a.isdigit() or b.isdigit():
        return 1.0 if a == b else 0.0          # "KV No. 1" must never match "KV No. 2"
    if len(a) == 1 or len(b) == 1:
        return 0.85 if a[0] == b[0] else 0.0   # initials: "L K Pandit"
    ca, cb = canon(a), canon(b)
    if ca == cb:
        return 0.97
    s = jaro_winkler(ca, cb)
    sa, sb = skeleton(a), skeleton(b)
    if len(sa) >= 3 and sa == sb:
        s = max(s, 0.92)
    short, long_ = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    if len(short) >= 4 and long_.startswith(short):
        s = max(s, 0.86)
    return s


def _cover(a: List[str], b: List[str]):
    """Weighted share of a's tokens found in b, and how many of b's tokens were used."""
    used, total, weight = set(), 0.0, 0.0
    for at in a:
        best, best_j = 0.0, None
        for j, bt in enumerate(b):
            if j in used:
                continue
            s = token_sim(at, bt)
            if s > best:
                best, best_j = s, j
        w = max(len(at), 2)
        total += best * w
        weight += w
        if best_j is not None and best >= 0.8:
            used.add(best_j)
    return total / weight, len(used)


def name_similarity(q: List[str], r: List[str]) -> float:
    """How well a query matches a record. Either side may carry extra words: the record a
    surname the coordinator didn't say, or a poster a middle name the directory doesn't store
    ("Rupali Shrikant Desai" against "Rupali Desai")."""
    if not q or not r:
        return 0.0
    cov_q, used_r = _cover(q, r)
    score = cov_q - min(0.12, 0.03 * (len(r) - used_r))
    digits = {t for t in q if t.isdigit()}
    if digits and not digits.issubset(r):
        return min(score, 0.7)                      # a different number is a different institution
    if len(r) >= 2:
        cov_r, used_q = _cover(r, q)
        score = max(score, cov_r - min(0.15, 0.05 * (len(q) - used_q)))
    joined = jaro_winkler(canon(''.join(q)), canon(''.join(r)))   # "hariprasad" vs "hari prasad"
    return max(score, joined - 0.02)


# ── People ────────────────────────────────────────────────────────────────────
def person_tokens(name: str) -> Tuple[List[str], dict]:
    toks = normalize(name).split()
    flags = {'deceased': False}
    while len(toks) > 1:
        t0 = toks[0]
        if t0 in DECEASED_MARKERS:
            flags['deceased'] = True; toks.pop(0)
        elif t0 == 'padma' and toks[1] in PADMA_FOLLOWERS and len(toks) > 2:
            del toks[:2]
        elif t0 == 'bharat' and toks[1] == 'ratna' and len(toks) > 2:
            del toks[:2]
        elif t0 == 'sangeet' and toks[1:3] == ['natak', 'akademi'] and len(toks) > 3:
            del toks[:3]
            if len(toks) > 1 and toks[0] in ('awardee', 'award'):
                toks.pop(0)
        elif t0 in LEADING_HONORIFICS:
            toks.pop(0)
        else:
            break
    while len(toks) > 1 and toks[-1] in TRAILING_HONORIFICS:
        toks.pop()
    if len(toks) > 1 and toks[-1] in DECEASED_MARKERS:
        flags['deceased'] = True; toks.pop()
    return toks, flags


def split_multi(value) -> List[str]:
    """'Vocal, Harmonium' / 'Sitar & Surbahar' -> separate art forms (reviewer DC10)."""
    if not value:
        return []
    parts = re.split(r'\s*(?:,|/|&|\+|;|\band\b)\s*', str(value))
    return [p.strip() for p in parts if p and p.strip() and p.strip().lower() != 'none']


# ── Institutions ─────────────────────────────────────────────────────────────
INSTITUTION_ABBREVIATIONS = {
    'iit': 'indian institute of technology', 'iitb': 'indian institute of technology mumbai',
    'iitd': 'indian institute of technology delhi', 'iitm': 'indian institute of technology chennai',
    'iitk': 'indian institute of technology kanpur', 'iitkgp': 'indian institute of technology kharagpur',
    'iitr': 'indian institute of technology roorkee', 'iitg': 'indian institute of technology guwahati',
    'iith': 'indian institute of technology hyderabad', 'nit': 'national institute of technology',
    'iiit': 'indian institute of information technology', 'iim': 'indian institute of management',
    'iisc': 'indian institute of science', 'iiser': 'indian institute of science education and research',
    'aiims': 'all india institute of medical sciences', 'bits': 'birla institute of technology and science',
    'nift': 'national institute of fashion technology', 'nid': 'national institute of design',
    'tiss': 'tata institute of social sciences', 'tifr': 'tata institute of fundamental research',
    'kv': 'kendriya vidyalaya', 'jnv': 'jawahar navodaya vidyalaya', 'dps': 'delhi public school',
    'aps': 'army public school', 'dav': 'dayanand anglo vedic', 'zp': 'zilla parishad',
    'zphs': 'zilla parishad high school', 'ghss': 'government higher secondary school',
    'gsss': 'government senior secondary school', 'gbsss': 'government boys senior secondary school',
    'ggsss': 'government girls senior secondary school', 'skv': 'sarvodaya kanya vidyalaya',
    'sbv': 'sarvodaya bal vidyalaya', 'rpvv': 'rajkiya pratibha vikas vidyalaya',
    'jnu': 'jawaharlal nehru university', 'du': 'university of delhi', 'bhu': 'banaras hindu university',
    'amu': 'aligarh muslim university', 'jmi': 'jamia millia islamia',
    'govt': 'government', 'gov': 'government', 'sr': 'senior', 'sec': 'secondary', 'hr': 'higher',
    'hs': 'high school', 'hss': 'higher secondary school', 'sss': 'senior secondary school',
    'sch': 'school', 'schl': 'school', 'coll': 'college', 'clg': 'college', 'univ': 'university',
    'uni': 'university', 'inst': 'institute', 'instt': 'institute', 'tech': 'technology',
    'engg': 'engineering', 'mgmt': 'management', 'intl': 'international', 'natl': 'national',
    'acad': 'academy', 'vidyalay': 'vidyalaya', 'vidhyalaya': 'vidyalaya', 'pub': 'public',
    'st': 'saint', 'mt': 'mount',
}
CITY_ALIASES = {
    'bombay': 'mumbai', 'madras': 'chennai', 'calcutta': 'kolkata', 'bangalore': 'bengaluru',
    'poona': 'pune', 'gurgaon': 'gurugram', 'baroda': 'vadodara', 'trivandrum': 'thiruvananthapuram',
    'cochin': 'kochi', 'mysore': 'mysuru', 'benaras': 'varanasi', 'banaras': 'varanasi',
    'benares': 'varanasi', 'allahabad': 'prayagraj', 'calicut': 'kozhikode', 'pondicherry': 'puducherry',
    'simla': 'shimla', 'orissa': 'odisha', 'cawnpore': 'kanpur', 'mangalore': 'mangaluru',
    'belgaum': 'belagavi', 'hubli': 'hubballi', 'tanjore': 'thanjavur', 'trichy': 'tiruchirappalli',
    'vizag': 'visakhapatnam', 'gauhati': 'guwahati', 'bhubaneshwar': 'bhubaneswar',
}
_STOP = frozenset({'of', 'the', 'and', 'for', 'at', 'in', 'de', 'a', 'an'})
CAMPUS_WORDS = frozenset({'campus', 'branch', 'centre', 'center', 'unit', 'wing'})
_ROMAN = {'i': '1', 'ii': '2', 'iii': '3', 'iv': '4', 'v': '5', 'vi': '6', 'vii': '7',
          'viii': '8', 'ix': '9', 'x': '10'}


def institution_tokens(text: str) -> List[str]:
    s = re.sub(r'\b(?:no|number|num)\s*(\d+)\b', r'\1', normalize(text))
    toks, out, i = s.split(), [], 0
    while i < len(toks):
        t = toks[i]
        if t in ('no', 'number') and i + 1 < len(toks) and toks[i + 1] in _ROMAN:
            i += 1
            continue
        if t in _ROMAN and out and out[-1] in ('vidyalaya', 'school', 'sector', 'phase'):
            t = _ROMAN[t]
        expanded = INSTITUTION_ABBREVIATIONS.get(t)
        if expanded:
            out.extend(w for w in expanded.split() if w not in _STOP)
        else:
            t = CITY_ALIASES.get(t, t)
            if t not in _STOP:
                out.append(t)
        i += 1
    return out


def plain_tokens(text: str) -> List[str]:
    return [t for t in normalize(text).split() if t not in _STOP]


# ── Money (Indian grouping) ──────────────────────────────────────────────────
def to_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r'(?i)(rs\.?|inr|rupees|\u20b9|/-|,|\s)', '', str(value))
    try:
        return float(s)
    except ValueError:
        return None


def inr(amount) -> str:
    n = to_number(amount)
    if n is None:
        return str(amount or '')
    neg, whole = n < 0, int(round(abs(n)))
    s = str(whole)
    if len(s) > 3:
        head = re.sub(r'(\d)(?=(\d{2})+$)', r'\1,', s[:-3])
        s = f'{head},{s[-3:]}'
    return ('-' if neg else '') + s


_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
         'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen',
         'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _two(n):
    return _ONES[n] if n < 20 else _TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else '')


def _three(n):
    h, r = divmod(n, 100)
    return ' '.join(x for x in ((_ONES[h] + ' Hundred') if h else '', _two(r) if r else '') if x)


def number_to_words_indian(n: int) -> str:
    if n == 0:
        return 'Zero'
    parts = []
    crore, n = divmod(n, 10 ** 7)
    lakh, n = divmod(n, 10 ** 5)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(number_to_words_indian(crore) + ' Crore')
    if lakh:
        parts.append(_two(lakh) + ' Lakh')
    if thousand:
        parts.append(_two(thousand) + ' Thousand')
    if n:
        parts.append(_three(n))
    return ' '.join(parts)


def amount_in_words(amount) -> str:
    n = to_number(amount)
    if n is None:
        return ''
    return f'Rupees {number_to_words_indian(int(round(abs(n))))} Only'


# ── Misc ─────────────────────────────────────────────────────────────────────
def mask_account(acc) -> str:
    s = re.sub(r'\s', '', str(acc or ''))
    return ('X' * max(len(s) - 4, 0) + s[-4:]) if s else ''


_EMOJI_RE = re.compile('[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]')


def clean_for_speech(text: str, limit: int = 600) -> str:
    """Strip markdown, links and emoji so a reply reads naturally aloud."""
    s = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', str(text or ''))
    s = re.sub(r'https?://\S+', '', s)
    s = re.sub(r'[*_`#>|]', '', s)
    s = _EMOJI_RE.sub('', s)
    s = re.sub(r'^\s*[-\u2022]\s*', '', s, flags=re.M)
    s = re.sub(r'\s+', ' ', s).strip()
    if len(s) > limit:
        cut = s[:limit].rsplit('. ', 1)[0]
        s = cut + '.'
    return s
