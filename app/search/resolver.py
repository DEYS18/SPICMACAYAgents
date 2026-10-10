"""
Directory search for artists, institutions and coordinators.

Why this replaced the SQL LIKE/SOUNDEX search:
- whole-string LIKE/SOUNDEX missed a slightly mis-spelt name as soon as the stored record
  carried a title or an extra word ("Shahid Pervez" vs "Ustad Shahid Parvez Khan");
- the abbreviations coordinators use every day (KV, JNV, DPS, IIT...) never matched the
  expanded names stored in the directory, and vice versa;
- several campuses of one institution (BITS Pilani: Pilani, Goa, Hyderabad, Dubai) were
  indistinguishable (reviewer comment DC4);
- similar-sounding artists were not surfaced for an art-form check (DC3).

The directory (~1.2k artists, ~5.3k institutions) is small enough to index in memory, so
each query is scored token by token with Indian-spelling-aware phonetics. The index
refreshes every few minutes and immediately after the assistant adds a record.
"""
import logging
import threading
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from app.core import text_utils as tu

logger = logging.getLogger(__name__)

ARTISTS_SQL = ("SELECT tid, name, art_form, artist_type, artist_grade, select_award, city, "
               "enter_state AS state, email, phone, added_by, "
               "CASE WHEN account_number IS NOT NULL AND account_number <> '' AND account_number <> 'None' "
               "THEN 1 ELSE 0 END AS has_bank FROM artists_list WHERE status = 1")
INSTITUTIONS_SQL = ("SELECT sid, institution_name, city, state, pincode, email, phone, address, "
                    "name_of_the_coordinator, institution_coordinator_designation, added_by "
                    "FROM institution_list WHERE status = 1")
USERS_SQL = "SELECT uid, name, mail FROM users_field_data WHERE status = 1 AND mail IS NOT NULL AND mail <> ''"
RECENT_ARTISTS_SQL = ("SELECT artist FROM event_list WHERE status = 1 AND artist IS NOT NULL "
                      "AND artist <> '' ORDER BY id DESC LIMIT 400")


def band(score: float) -> str:
    return 'exact' if score >= 0.95 else 'strong' if score >= 0.86 else 'possible' if score >= 0.74 else 'weak'


def _clean(v):
    v = '' if v is None else str(v).strip()
    return '' if v.lower() == 'none' else v


def make_db_loaders(db) -> dict:
    def q(sql):
        try:
            return db.fetch_all(sql) or []
        except Exception as e:
            logger.error('Directory load failed: %s', e)
            return []
    return {
        'load_artists': lambda: q(ARTISTS_SQL),
        'load_institutions': lambda: q(INSTITUTIONS_SQL),
        'load_users': lambda: q(USERS_SQL),
        'load_recent_artist_ids': lambda: [str(r.get('artist')) for r in q(RECENT_ARTISTS_SQL)],
    }


class DirectoryIndex:
    def __init__(self, load_artists, load_institutions, load_users=None, load_recent_artist_ids=None,
                 flags_provider=None, ttl_seconds: int = 600):
        self._load_artists, self._load_institutions = load_artists, load_institutions
        self._load_users, self._load_recent = load_users, load_recent_artist_ids
        self._flags = flags_provider
        self._ttl = ttl_seconds
        self._lock = threading.RLock()
        self._loaded_at = 0.0
        self._artists, self._insts, self._coords, self._recent = [], [], [], []
        self._artist_by_id, self._inst_by_id, self._inst_prefix = {}, {}, defaultdict(set)

    # ── loading ──────────────────────────────────────────────────────────────
    def invalidate(self):
        self._loaded_at = 0.0

    def _ensure(self):
        if time.time() - self._loaded_at > self._ttl:
            self.refresh()

    def refresh(self):
        with self._lock:
            flags = []
            if self._flags:
                try:
                    flags = [f for f in (self._flags() or []) if f.get('entity') == 'artist']
                except Exception as e:
                    logger.warning('Directory flags unavailable: %s', e)
            self._artists = [self._artist_rec(r, flags) for r in (self._load_artists() or []) if _clean(r.get('name'))]
            self._artist_by_id = {str(a['data']['tid']): a for a in self._artists}
            self._insts, self._inst_prefix = [], defaultdict(set)
            for r in (self._load_institutions() or []):
                if not _clean(r.get('institution_name')):
                    continue
                rec = self._inst_rec(r)
                idx = len(self._insts)
                self._insts.append(rec)
                for t in rec['tokens'] + rec['city']:
                    if len(t) >= 2:
                        self._inst_prefix[tu.canon(t)[:2]].add(idx)
                if rec['acronym']:
                    self._inst_prefix[rec['acronym'][:2]].add(idx)
            self._inst_by_id = {str(i['data']['sid']): i for i in self._insts}
            self._coords = self._coordinator_recs()
            try:
                self._recent = list(self._load_recent() or []) if self._load_recent else []
            except Exception:
                self._recent = []
            self._loaded_at = time.time()
            logger.info('Directory index: %d artists, %d institutions, %d coordinators',
                        len(self._artists), len(self._insts), len(self._coords))

    def _artist_rec(self, row, flags):
        toks, f = tu.person_tokens(row.get('name'))
        rec = {'data': row, 'tokens': toks, 'aux': tu.plain_tokens(_clean(row.get('art_form'))), 'flags': set()}
        if f['deceased']:
            rec['flags'].add('deceased')
        if _clean(row.get('added_by')).upper().startswith('AI-PROV'):
            rec['flags'].add('provisional')
        surnames = {tu.canon(t) for t in toks}
        for fl in flags:
            if fl.get('ref_id') and str(fl['ref_id']) == str(row.get('tid')):
                rec['flags'].add(fl.get('flag') or 'flagged')
                continue
            ft = tu.person_tokens(fl.get('name') or '')[0]
            if not ft or tu.canon(ft[-1]) not in surnames:
                continue
            if min(tu.name_similarity(ft, toks), tu.name_similarity(toks, ft)) >= 0.93:
                af = tu.plain_tokens(fl.get('art_form') or '')
                if not af or not rec['aux'] or max(tu.name_similarity(af, rec['aux']), tu.name_similarity(rec['aux'], af)) >= 0.8:
                    rec['flags'].add(fl.get('flag') or 'flagged')
        return rec

    def _inst_rec(self, row):
        toks = tu.institution_tokens(row.get('institution_name'))
        city = tu.institution_tokens(_clean(row.get('city')))
        base = [t for t in toks if t not in city and t not in tu.CAMPUS_WORDS]
        place = city + [t for t in tu.institution_tokens(_clean(row.get('address'))) if t not in city]
        return {'data': row, 'tokens': toks, 'city': city, 'place': place, 'state': tu.plain_tokens(_clean(row.get('state'))),
                'base': base or toks, 'acronym': ''.join(t[0] for t in toks if not t.isdigit())}

    def _coordinator_recs(self):
        out = []
        for u in (self._load_users() if self._load_users else []) or []:
            email = _clean(u.get('mail'))
            if not email:
                continue
            local = email.split('@')[0]
            uname = _clean(u.get('name'))
            out.append({'source': 'user', 'uid': u.get('uid'), 'name': uname.title() if uname.islower() else uname, 'email': email,
                        'institution_name': None, 'tokens': tu.person_tokens(u.get('name') or '')[0],
                        'email_tokens': [t for t in tu.normalize(local.replace('.', ' ').replace('_', ' ')).split() if not t.isdigit()]})
        for rec in self._insts:
            d = rec['data']
            name, email = _clean(d.get('name_of_the_coordinator')), _clean(d.get('email'))
            if name and email:
                out.append({'source': 'institution', 'uid': None, 'name': name, 'email': email,
                            'institution_name': d.get('institution_name'), 'tokens': tu.person_tokens(name)[0],
                            'email_tokens': []})
        return out

    # ── artists ──────────────────────────────────────────────────────────────
    def _artist_out(self, rec, score):
        d = rec['data']
        return {'tid': d.get('tid'), 'name': _clean(d.get('name')), 'art_form': _clean(d.get('art_form')),
                'art_forms': tu.split_multi(_clean(d.get('art_form'))), 'artist_type': _clean(d.get('artist_type')),
                'grade': _clean(d.get('artist_grade')), 'award': _clean(d.get('select_award')),
                'city': _clean(d.get('city')), 'state': _clean(d.get('state')), 'email': _clean(d.get('email')),
                'phone': _clean(d.get('phone')), 'has_bank': bool(int(d.get('has_bank') or 0)),
                'score': round(min(float(score), 1.0), 3), 'band': band(score), 'flags': sorted(rec['flags']),
                'provisional': 'provisional' in rec['flags']}

    def search_artists(self, query: str, art_form: str = None, limit: int = 8) -> dict:
        self._ensure()
        qt, qf = tu.person_tokens(query or '')
        out = {'query': query, 'matches': [], 'ambiguous': False, 'best': None, 'said_late': qf['deceased']}
        if not qt:
            return out
        af = tu.plain_tokens(art_form) if art_form else []
        scored = []
        for i, rec in enumerate(self._artists):       # ~1.2k records: a full scan is cheap
            s = tu.name_similarity(qt, rec['tokens'])
            if s < 0.6:
                continue
            if af and rec['aux']:
                a = max(tu.name_similarity(af, rec['aux']), tu.name_similarity(rec['aux'], af))
                s += 0.06 if a >= 0.85 else -0.08
            scored.append((s, i))           # ranked uncapped, so an art-form or place bonus still separates two exact names
        scored.sort(key=lambda x: -x[0])
        out['matches'] = [self._artist_out(self._artists[i], s) for s, i in scored[:limit]]
        out['ambiguous'] = len(scored) > 1 and scored[0][0] - scored[1][0] < 0.04 and scored[1][0] >= 0.8
        out['best'] = out['matches'][0] if scored and scored[0][0] >= 0.86 and not out['ambiguous'] else None
        return out

    def get_artist(self, tid) -> Optional[dict]:
        self._ensure()
        rec = self._artist_by_id.get(str(tid))
        return self._artist_out(rec, 1.0) if rec else None

    def popular_artist_names(self, n: int = 20) -> List[str]:
        self._ensure()
        counts = Counter(i for i in self._recent if i in self._artist_by_id)
        return [self._artist_by_id[i]['data'].get('name') for i, _ in counts.most_common(n)]

    # ── institutions ─────────────────────────────────────────────────────────
    def _inst_out(self, rec, score):
        d = rec['data']
        return {'sid': d.get('sid'), 'institution_name': _clean(d.get('institution_name')),
                'city': _clean(d.get('city')), 'state': _clean(d.get('state')), 'pincode': _clean(d.get('pincode')),
                'email': _clean(d.get('email')), 'phone': _clean(d.get('phone')),
                'name_of_the_coordinator': _clean(d.get('name_of_the_coordinator')),
                'provisional': _clean(d.get('added_by')).upper().startswith('AI-PROV'),
                'score': round(min(float(score), 1.0), 3), 'band': band(score)}

    def search_institutions(self, query: str, city: str = None, state: str = None, limit: int = 8) -> dict:
        self._ensure()
        qt = tu.institution_tokens(query or '')
        raw = tu.normalize(query or '').split()
        out = {'query': query, 'matches': [], 'ambiguous': False, 'best': None, 'campus_choices': None}
        if not qt:
            return out
        keys = {tu.canon(t)[:2] for t in qt + raw if len(t) >= 2}
        cands = set()
        for k in keys:
            cands |= self._inst_prefix.get(k, set())
        if len(cands) < 25:
            cands = range(len(self._insts))
        cq = tu.institution_tokens(city) if city else []
        sq = tu.plain_tokens(state) if state else []
        distinct = [t for t in qt if t not in _GENERIC_INST and not t.isdigit() and len(t) > 2]
        scored = []
        for i in cands:
            rec = self._insts[i]
            s = tu.name_similarity(qt, rec['tokens'])
            if rec['city']:
                s = max(s, tu.name_similarity(qt, rec['tokens'] + [c for c in rec['city'] if c not in rec['tokens']]) - 0.01)
            acronym = bool(rec['acronym'] and len(rec['acronym']) >= 3 and rec['acronym'] in raw)
            if acronym:
                s = max(s, 0.9)
            if s < 0.6:
                continue
            if cq:
                s += 0.06 if _place_hit(cq, rec['place'] + rec['tokens']) else -0.05
            if sq and rec['state']:
                s += 0.03 if tu.name_similarity(sq, rec['state']) >= 0.85 else -0.03
            if distinct and not acronym:
                words = [w for w in rec['tokens'] + rec['place'] if len(w) > 1]   # initials match people, not institutions
                if any(max((tu.token_sim(t, w) for w in words), default=0) < 0.8 for t in distinct):
                    s = min(s, 0.84)        # a distinctive word is missing: offer it, never pick it automatically
            scored.append((s, i))           # ranked uncapped: a matching city must still win over a namesake elsewhere
        scored.sort(key=lambda x: -x[0])
        top = scored[:limit]
        out['matches'] = [self._inst_out(self._insts[i], s) for s, i in top]
        m = out['matches']
        out['ambiguous'] = len(top) > 1 and top[0][0] - top[1][0] < 0.04 and top[1][0] >= 0.8
        # Campuses: several strong matches sharing a base name but in different cities
        if top and top[0][0] >= 0.8:
            anchor = self._insts[top[0][1]]['base']
            group = [(s, i) for s, i in top if s >= 0.78 and max(
                tu.name_similarity(anchor, self._insts[i]['base']),
                tu.name_similarity(self._insts[i]['base'], anchor)) >= 0.9]
            cities = {(self._insts[i]['data'].get('city') or '').strip().lower() for _, i in group}
            if len(group) > 1 and len(cities) > 1:
                if cq:
                    in_city = [(s, i) for s, i in group if _place_hit(cq, self._insts[i]['place'] + self._insts[i]['tokens'])]
                    if len(in_city) == 1:
                        group = []
                if group:
                    out['campus_choices'] = [self._inst_out(self._insts[i], s) for s, i in group]
        # An exact name wins unless another record has that same name. Real directories carry unreliable city
        # fields (often the last word of the name), which would otherwise look like several campuses.
        key, qset = ' '.join(qt), set(qt)
        exact = [(s, i) for s, i in top if ' '.join(self._insts[i]['tokens']) == key]
        # ...but genuine campuses of it ("BITS Pilani Goa Campus" for "BITS Pilani") keep the campus question (DC4)
        more_specific = [i for s, i in top if s >= 0.78 and qset < set(self._insts[i]['tokens'])]
        if cq and len(exact) > 1:
            exact = [(s, i) for s, i in exact if _place_hit(cq, self._insts[i]['place'] + self._insts[i]['tokens'])] or exact
        if len(exact) == 1 and not more_specific:
            out['ambiguous'], out['campus_choices'] = False, None
            top = [exact[0]] + [t for t in top if t[1] != exact[0][1]]
            out['matches'] = m = [self._inst_out(self._insts[i], s) for s, i in top]
        elif len(exact) > 1:
            out['ambiguous'] = True
            out['campus_choices'] = [self._inst_out(self._insts[i], s) for s, i in exact]
        out['best'] = m[0] if top and top[0][0] >= 0.86 and not out['ambiguous'] and not out['campus_choices'] else None
        if cq and top and not any(_place_hit(cq, self._insts[i]['place'] + self._insts[i]['tokens']) for _, i in top[:5]):
            out['city_mismatch'] = True             # e.g. a new campus that isn't in the directory yet
        return out

    def get_institution(self, sid) -> Optional[dict]:
        self._ensure()
        rec = self._inst_by_id.get(str(sid))
        return self._inst_out(rec, 1.0) if rec else None

    # ── coordinators ─────────────────────────────────────────────────────────
    def search_coordinators(self, query: str, limit: int = 5) -> dict:
        self._ensure()
        q = (query or '').strip()
        if '@' in q:
            hits = [c for c in self._coords if c['email'].lower() == q.lower()]
            return {'query': q, 'matches': [dict(_strip(c), score=1.0) for c in hits[:limit]]}
        qt = tu.person_tokens(q)[0]
        best: Dict[str, dict] = {}
        for c in self._coords:
            s = max(tu.name_similarity(qt, c['tokens']) if c['tokens'] else 0,
                    tu.name_similarity(qt, c['email_tokens']) - 0.03 if c['email_tokens'] else 0)
            if s >= 0.75:
                key = c['email'].lower()
                if key not in best or s > best[key]['score']:
                    best[key] = dict(_strip(c), score=round(s, 3))
        return {'query': q, 'matches': sorted(best.values(), key=lambda x: -x['score'])[:limit]}

    def find_coordinator_by_email(self, email: str) -> Optional[dict]:
        r = self.search_coordinators(email or '', 1)['matches'] if email and '@' in email else []
        return r[0] if r else None


# Words that say what kind of institution it is, not which one. A match needs the other words too.
_GENERIC_INST = {'institute', 'institution', 'school', 'college', 'university', 'vidyalaya', 'vidyalay', 'mahavidyalaya', 'public',
                 'senior', 'secondary', 'sec', 'sr', 'high', 'higher', 'govt', 'government', 'national', 'technology', 'science',
                 'sciences', 'arts', 'commerce', 'academy', 'centre', 'center', 'campus', 'international', 'english', 'medium',
                 'convent', 'model', 'primary', 'middle', 'girls', 'boys', 'inter', 'degree', 'polytechnic', 'engineering',
                 'management', 'research', 'studies', 'education', 'educational', 'society', 'trust', 'foundation', 'india',
                 'indian', 'all', 'saint', 'sri', 'shri', 'new', 'kendriya', 'no', 'department', 'faculty', 'medical', 'music',
                 'fine', 'performing', 'deemed', 'autonomous', 'women', 'womens', 'and', 'of', 'the'}
_GENERIC_PLACE = {'east', 'west', 'north', 'south', 'new', 'old', 'city', 'district', 'dist', 'road', 'nagar'}


def _place_hit(hint_tokens, place_tokens):
    keys = [t for t in hint_tokens if t not in _GENERIC_PLACE and len(t) >= 3] or hint_tokens
    return any(max((tu.token_sim(k, p) for p in place_tokens), default=0) >= 0.9 for k in keys)


def _strip(c):
    return {k: c[k] for k in ('source', 'uid', 'name', 'email', 'institution_name')}
