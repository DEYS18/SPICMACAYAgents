"""Batch filing with the ten real posters, end to end through the HTTP API."""
import base64
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import FakeLLM, build_test_services  # noqa: E402
from real_world import POSTERS, UNKNOWN_ARTISANS, seed_real_world  # noqa: E402

from app.assistant_setup import create_assistant_app  # noqa: E402
from app.services import pdf_service, poster_service  # noqa: E402


def tiny_jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (60, 80), (240, 200, 40)).save(buf, 'JPEG')
    return base64.b64encode(buf.getvalue()).decode()


class RealPosterTests(unittest.TestCase):
    def setUp(self):
        self.llm = FakeLLM()
        self.s, self.db, self.tmp = build_test_services(self.llm)
        seed_real_world(self.db)
        self.s.index.invalidate()
        self.s.gov.set_setting('batch.parallel_reads', 1, 'test')
        self._dirs = poster_service._ARTIST_PHOTO_DIR, pdf_service.EVENT_PHOTOS_DIR
        poster_service._ARTIST_PHOTO_DIR = os.path.join(self.tmp, 'artist_photos')
        pdf_service.EVENT_PHOTOS_DIR = os.path.join(self.tmp, 'event_photos')
        self.c = create_assistant_app(self.s).test_client()

    def tearDown(self):
        poster_service._ARTIST_PHOTO_DIR, pdf_service.EVENT_PHOTOS_DIR = self._dirs

    def upload(self):
        for _, data in POSTERS:
            self.llm.push({'content': json.dumps(data)})
        j = self.c.post('/api/assistant/batch', json={'files': [{'filename': f, 'mime': 'image/jpeg', 'data': tiny_jpeg()} for f, _ in POSTERS]}).get_json()
        return j, self.card(j)

    def act(self, type_, **payload):
        return self.c.post('/api/assistant/action', json={'type': type_, 'payload': payload}).get_json()

    @staticmethod
    def card(j, kind='batch_plan'):
        return next((c for c in j['ui']['cards'] if c['type'] == kind), None)

    @staticmethod
    def prog(card, start):
        return next(p for p in card['programs'] if p['title'].startswith(start))

    def resolve_everything(self):
        _, card = self.upload()
        self.act('batch_coordinator', email='sabyasachi@spicmacay.com')
        nps = self.prog(card, 'Virasat 2026: Nalanda')
        yoga = next(e for e in nps['events'] if 'Ambika' in e['artist'])
        self.act('batch_toggle', pid=nps['pid'], eid=yoga['eid'], include=False)
        for name, form in UNKNOWN_ARTISANS:
            self.act('batch_add', pid=nps['pid'], kind='artist', said=name, role='main', art_form=form)
        bits = self.prog(card, 'BITS') if any(p['title'].startswith('BITS') for p in card['programs']) else \
            next(p for p in card['programs'] if any('BITS' in e['place'] for e in p['events']))
        return self.card(self.act('batch_add', pid=bits['pid'], kind='institution', said='BITS Pilani Mumbai Campus',
                                  name='BITS Pilani Mumbai Campus', city='Kalyan', state='Maharashtra'))

    def test_the_plan_from_ten_posters(self):
        j, card = self.upload()
        self.assertIn('10 of 10 posters', j['reply'])
        self.assertEqual(len(card['programs']), 6)
        self.assertEqual(len(card['merged']), 2)                      # poster 2 into the Virasat concert; the two TISS posters
        self.assertEqual(len(card['skipped']), 1)                     # the film screening needs no APR
        self.assertTrue(card['needs_coordinator'])
        nps = self.prog(card, 'Virasat 2026: Nalanda')
        self.assertEqual((nps['type'], len(nps['events']), nps['status']), ('virasat', 11, 'needs_attention'))
        concert = next(e for e in nps['events'] if e['when'].startswith('9 Sep') and 'Suranjana' in e['artist'])
        self.assertIn('Milind Naik', concert['artist'])               # accompanists from the single-concert poster
        self.assertEqual({u['said'] for u in nps['unresolved']}, {n for n, _ in UNKNOWN_ARTISANS} | {'Ambika Yog Kutir'})
        circuit = self.prog(card, 'Circuit: Suranjana Bose')
        self.assertEqual(([e['place'] for e in circuit['events']], circuit['status']),
                         (['Heritage International School', 'Tata Institute of Fundamental Research'], 'ready'))
        self.assertTrue(any('Virasat' in w for w in circuit['warnings']))
        vnit = self.prog(card, 'Virasat 2026: Visvesvaraya')
        self.assertEqual((len(vnit['events']), vnit['status']), (2, 'ready'))
        bits = next(p for p in card['programs'] if any('BITS' in e['place'] for e in p['events']))
        self.assertEqual(bits['status'], 'needs_attention')
        self.assertTrue(next(u for u in bits['unresolved'] if u['kind'] == 'institution')['city_mismatch'])
        self.assertIn('Parveen Sultana', bits['events'][0]['artist'])   # poster said Parween
        self.assertIn('Akram Khan', bits['events'][0]['artist'])
        tiss = next(p for p in card['programs'] if 'Lalgudi' in p['events'][0]['artist'])
        self.assertEqual((tiss['status'], tiss['events'][0]['place']), ('ready', 'Tata Institute of Social Sciences'))
        self.assertIn('B.C. Manjunath', tiss['events'][0]['artist'])
        rupak = next(p for p in card['programs'] if 'Rupak' in p['events'][0]['artist'])
        self.assertEqual((rupak['status'], rupak['events'][0]['place']), ('ready', "St. Mary's ICSE School"))

    def test_file_all_then_choose_payment_requests(self):
        card = self.resolve_everything()
        self.assertEqual([p['status'] for p in card['programs']].count('ready'), 6, [(p['title'], p['issues']) for p in card['programs']])
        self.assertEqual(card['button'], 'File 6 APRs')
        j = self.act('confirm', confirmation_id=card['confirmation_id'])
        self.assertIn('Filed **6 APRs**', j['reply'])
        results = self.card(j, 'batch_results')['results']
        self.assertEqual(sorted(r['apr_number'] for r in results), ['208', '209', '210', '211', '212', '213'])
        # multi-day workshops are one row per day: Nalanda 7 workshops x 3 days + 3 concerts, VNIT 1 + 2 days
        self.assertEqual((self.db.count('event_list'), self.db.count('apr_payment_request'), self.db.count('event_series')), (32, 32, 3))
        vnit = [r['start_date'] for r in self.db.fetch_all("SELECT start_date FROM event_list WHERE institution = 'Visvesvaraya National Institute of Technology' ORDER BY start_date")]
        self.assertEqual(vnit, ['2026-09-24', '2026-09-25', '2026-09-26'])
        self.assertTrue(all(r['start_date'] == r['end_date'] for r in self.db.fetch_all('SELECT start_date, end_date FROM event_list')))
        mods = {r['event_category'] for r in self.db.fetch_all('SELECT event_category FROM event_list')}
        self.assertEqual(mods, {'13', '9'})                              # Full Concert and Workshops, as module ids
        audit = self.s.gov.list_audit(300)
        apr_mails = [a for a in audit if a['action'] == 'email.dry_run' and a['target'] == 'apr_confirmation']
        self.assertEqual(len(apr_mails), 6)
        self.assertTrue(all('sabyasachi@spicmacay.com' in a['details']['to'] for a in apr_mails))
        for r in results:
            self.assertTrue(os.path.exists(self.s.files.path('apr', r['pdf_file'])))
        rows = self.card(j, 'rfp_picker')['rows']
        tiss = next(r for r in rows if 'Social' in r['institution'])
        bits = next(r for r in rows if 'BITS' in r['institution'])
        j = self.act('batch_rfp', rows=[{'event_ids': tiss['event_ids'], 'amount': 15000, 'email': 'heritage@tiss.edu'},
                                        {'event_ids': bits['event_ids'], 'amount': 25000, 'email': 'heritage.club@bitsom.edu.in'}])
        out = self.card(j, 'outbox')
        self.assertEqual([i['status'] for i in out['items']], ['ready', 'ready'])
        self.assertEqual({i['amount_inr'] for i in out['items']}, {'15,000', '25,000'})
        nps = next(r for r in rows if 'Nalanda' in r['institution'])
        self.assertEqual(len(nps['event_ids']), 24)                     # every day of every Virasat session
        sent = self.act('confirm', confirmation_id=out['confirmation_id'])
        self.assertIn('Sent 2 emails', sent['reply'])

    def test_nothing_is_filed_twice(self):
        card = self.resolve_everything()
        self.act('confirm', confirmation_id=card['confirmation_id'])
        _, again = self.upload()
        self.assertEqual(again['ready'], 0)
        for p in again['programs']:
            filed = [e for e in p['events'] if e['existing']]
            self.assertTrue(all(not e['include'] for e in filed))
        self.assertEqual(self.db.count('event_list'), 32)

    def test_one_combined_email(self):
        card = self.resolve_everything()
        self.act('batch_email_mode', mode='combined')
        self.act('confirm', confirmation_id=self.card(self.act('batch_show'))['confirmation_id'], email_mode='combined')
        audit = self.s.gov.list_audit(300)
        combined = [a for a in audit if a['target'] == 'apr_batch_summary']
        self.assertEqual(len(combined), 1)
        self.assertEqual(len(combined[0]['details']['attachments']), 6)
        self.assertFalse([a for a in audit if a['action'] == 'email.dry_run' and a['target'] == 'apr_confirmation'])


if __name__ == '__main__':
    unittest.main()
