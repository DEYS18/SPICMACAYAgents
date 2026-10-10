"""
Looking beyond our own directory when an artist or institution isn't in it.

Sources, in order (each optional; every result is a *suggestion* for the coordinator to
confirm, never written silently):
- Artists: Wikipedia + Wikidata (no key; date of death, instrument, Padma / Sangeet Natak
  Akademi awards), then Google Knowledge Graph when GOOGLE_API_KEY is set.
- Institutions: Google Places (New) Text Search when GOOGLE_API_KEY is set, otherwise
  OpenStreetMap Nominatim (no key), then Wikipedia.
Results are cached for 30 days in the governance store.
"""
import json
import logging
import urllib.parse
import urllib.request
from typing import Callable, Optional

from app.core import text_utils as tu

logger = logging.getLogger(__name__)
UA = 'SPICMACAY-APR-Assistant/2.0 (+https://www.spicmacay.org)'
_ARTS_WORDS = ('music', 'musician', 'singer', 'vocalist', 'dancer', 'dance', 'player', 'sitar', 'tabla',
               'sarod', 'classical', 'carnatic', 'hindustani', 'instrumentalist', 'percussionist',
               'composer', 'bharatanatyam', 'kathak', 'odissi', 'flautist', 'violinist')
_AWARD_WORDS = ('padma', 'sangeet natak', 'bharat ratna', 'kalidas', 'sangita kalanidhi', 'kalaimamani')


def _default_fetch(url, headers=None, data=None, timeout=5):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'User-Agent': UA, **(headers or {})},
                                 method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


class WebEnricher:
    def __init__(self, cache=None, settings: Callable = None, google_api_key: str = '',
                 fetch_json: Callable = None):
        self.cache = cache
        self.settings = settings or (lambda k, d=None: d)
        self.key = google_api_key or ''
        self.fetch = fetch_json or _default_fetch

    @property
    def enabled(self) -> bool:
        return bool(self.settings('search.web_enrichment', True))

    def _cached(self, key, producer):
        if self.cache:
            hit = self.cache.cache_get(key, max_age_days=30)
            if hit is not None:
                return hit
        value = producer()
        if self.cache and value is not None:
            self.cache.cache_set(key, value)
        return value

    # ── artists ──────────────────────────────────────────────────────────────
    def lookup_artist(self, name: str, art_form: str = None) -> dict:
        if not self.enabled:
            return {'enabled': False, 'results': []}
        key = f"artist:{tu.normalize(name)}|{tu.normalize(art_form or '')}"
        return self._cached(key, lambda: {'enabled': True, 'results': self._artist_sources(name, art_form)})

    def _artist_sources(self, name, art_form):
        results = []
        try:
            results.extend(self._wikipedia_person(name, art_form))
        except Exception as e:
            logger.info('Wikipedia lookup failed: %s', e)
        if self.key and self.settings('search.google_kg', True):
            try:
                results.extend(self._google_kg(name))
            except Exception as e:
                logger.info('Knowledge Graph lookup failed: %s', e)
        return results[:4]

    def _wikipedia_person(self, name, art_form):
        q = urllib.parse.quote(f"{name} {art_form or ''} Indian classical".strip())
        data = self.fetch(f'https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=3&srsearch={q}')
        out, qt = [], tu.person_tokens(name)[0]
        for hit in (data.get('query', {}).get('search') or [])[:3]:
            title = hit.get('title', '')
            if tu.name_similarity(qt, tu.person_tokens(title)[0]) < 0.75:
                continue
            summ = self.fetch('https://en.wikipedia.org/api/rest_v1/page/summary/' + urllib.parse.quote(title.replace(' ', '_')))
            desc = (summ.get('description') or '') + ' ' + (summ.get('extract') or '')
            if not any(w in desc.lower() for w in _ARTS_WORDS):
                continue
            item = {'source': 'Wikipedia', 'name': summ.get('title') or title,
                    'description': summ.get('description') or '', 'extract': (summ.get('extract') or '')[:600],
                    'url': (summ.get('content_urls') or {}).get('desktop', {}).get('page', ''),
                    'thumbnail': (summ.get('thumbnail') or {}).get('source', ''), 'needs_confirmation': True}
            qid = summ.get('wikibase_item')
            if qid:
                item.update(self._wikidata(qid))
            out.append(item)
        return out

    def _wikidata(self, qid):
        ent = self.fetch(f'https://www.wikidata.org/w/api.php?action=wbgetentities&ids={qid}'
                         f'&props=claims&format=json').get('entities', {}).get(qid, {})
        claims = ent.get('claims', {})

        def ids(prop):
            vals = []
            for c in claims.get(prop, []):
                v = (c.get('mainsnak', {}).get('datavalue') or {}).get('value')
                if isinstance(v, dict) and v.get('id'):
                    vals.append(v['id'])
            return vals
        dod = None
        for c in claims.get('P570', []):
            v = (c.get('mainsnak', {}).get('datavalue') or {}).get('value') or {}
            if v.get('time'):
                dod = v['time'].lstrip('+')[:10]
        wanted = (ids('P1303') + ids('P136') + ids('P166'))[:45]
        labels = {}
        if wanted:
            lab = self.fetch('https://www.wikidata.org/w/api.php?action=wbgetentities&ids=' + '|'.join(wanted) +
                             '&props=labels&languages=en&format=json').get('entities', {})
            labels = {k: (v.get('labels', {}).get('en') or {}).get('value', '') for k, v in lab.items()}
        awards = [labels[i] for i in ids('P166') if any(w in labels.get(i, '').lower() for w in _AWARD_WORDS)]
        return {'deceased': bool(dod), 'date_of_death': dod,
                'instruments': [labels[i] for i in ids('P1303') if labels.get(i)],
                'genres': [labels[i] for i in ids('P136') if labels.get(i)], 'awards': awards}

    def _google_kg(self, name):
        q = urllib.parse.urlencode({'query': name, 'key': self.key, 'limit': 3, 'languages': 'en', 'types': 'Person'})
        data = self.fetch(f'https://kgsearch.googleapis.com/v1/entities:search?{q}')
        out = []
        for el in data.get('itemListElement', [])[:3]:
            r = el.get('result', {})
            desc = (r.get('description') or '') + ' ' + ((r.get('detailedDescription') or {}).get('articleBody') or '')
            if any(w in desc.lower() for w in _ARTS_WORDS):
                out.append({'source': 'Google Knowledge Graph', 'name': r.get('name'),
                            'description': r.get('description') or '',
                            'extract': ((r.get('detailedDescription') or {}).get('articleBody') or '')[:600],
                            'url': (r.get('detailedDescription') or {}).get('url', ''), 'needs_confirmation': True})
        return out

    # ── institutions ─────────────────────────────────────────────────────────
    def lookup_institution(self, name: str, city: str = None) -> dict:
        if not self.enabled:
            return {'enabled': False, 'results': []}
        key = f"inst:{tu.normalize(name)}|{tu.normalize(city or '')}"
        return self._cached(key, lambda: {'enabled': True, 'results': self._institution_sources(name, city)})

    def _institution_sources(self, name, city):
        q = f"{name} {city or ''} India".strip()
        for producer in ((self._places if self.key and self.settings('search.google_places', True) else None),
                         self._nominatim, self._wikipedia_place):
            if not producer:
                continue
            try:
                res = producer(q)
                if res:
                    return res[:5]
            except Exception as e:
                logger.info('Institution lookup via %s failed: %s', getattr(producer, '__name__', producer), e)
        return []

    def _places(self, q):
        data = self.fetch('https://places.googleapis.com/v1/places:searchText',
                          headers={'Content-Type': 'application/json', 'X-Goog-Api-Key': self.key,
                                   'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,'
                                   'places.addressComponents,places.websiteUri,places.nationalPhoneNumber,places.googleMapsUri'},
                          data={'textQuery': q, 'regionCode': 'IN', 'languageCode': 'en', 'maxResultCount': 5})
        out = []
        for p in data.get('places', []):
            comp = {t: c.get('longText') for c in p.get('addressComponents', []) for t in c.get('types', [])}
            out.append({'source': 'Google Places', 'name': (p.get('displayName') or {}).get('text'),
                        'address': p.get('formattedAddress'),
                        'city': comp.get('locality') or comp.get('administrative_area_level_3') or comp.get('sublocality'),
                        'state': comp.get('administrative_area_level_1'), 'pincode': comp.get('postal_code'),
                        'phone': p.get('nationalPhoneNumber'), 'website': p.get('websiteUri'),
                        'maps_url': p.get('googleMapsUri'), 'needs_confirmation': True})
        return out

    def _nominatim(self, q):
        url = 'https://nominatim.openstreetmap.org/search?' + urllib.parse.urlencode(
            {'q': q, 'format': 'jsonv2', 'addressdetails': 1, 'limit': 5, 'countrycodes': 'in'})
        data = self.fetch(url)
        out = []
        for p in data if isinstance(data, list) else []:
            a = p.get('address', {})
            out.append({'source': 'OpenStreetMap', 'name': (p.get('display_name') or '').split(',')[0],
                        'address': p.get('display_name'),
                        'city': a.get('city') or a.get('town') or a.get('village') or a.get('county'),
                        'state': a.get('state'), 'pincode': a.get('postcode'), 'needs_confirmation': True})
        return out

    def _wikipedia_place(self, q):
        data = self.fetch('https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=3&srsearch='
                          + urllib.parse.quote(q))
        return [{'source': 'Wikipedia', 'name': h.get('title'), 'needs_confirmation': True,
                 'url': 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(h.get('title', '').replace(' ', '_'))}
                for h in (data.get('query', {}).get('search') or [])[:3]]
