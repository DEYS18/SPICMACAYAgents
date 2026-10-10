"""Language core: dates (DC1), Indian names and scripts, institutions and campuses (DC3, DC4,
DC10), money, governance and document rendering."""
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ARTISTS, INSTITUTIONS  # noqa: E402

from app.core import dates as dt, text_utils as tu  # noqa: E402
from app.core.default_templates import DEFAULT_TEMPLATES, sample_context  # noqa: E402
from app.core.governance import Governance  # noqa: E402
from app.core.rendering import PdfRenderer, TemplateRenderer, org_context  # noqa: E402
from app.search.resolver import DirectoryIndex  # noqa: E402

T = date(2026, 10, 9)
A = [{'tid': a[0], 'name': a[1], 'art_form': a[2], 'city': a[3], 'state': a[4]} for a in ARTISTS]
I = [{'sid': i[0], 'institution_name': i[1], 'city': i[2], 'state': i[3]} for i in INSTITUTIONS]


class DateTests(unittest.TestCase):
    def check(self, text, iso, amb=None):
        p = dt.parse_date(text, T)
        self.assertIsNotNone(p, text)
        self.assertEqual(p.iso, iso, text)
        if amb is not None:
            self.assertEqual(p.ambiguous, amb, text)

    def test_any_format_dc1(self):
        for text, iso in [('15-10-2026', '2026-10-15'), ('15/10/26', '2026-10-15'), ('2026-10-15', '2026-10-15'),
                          ('15 Oct 2026', '2026-10-15'), ('15-Oct-2026', '2026-10-15'), ('October 15th, 2026', '2026-10-15'),
                          ('15th of October', '2026-10-15'), ('१५ अक्टूबर २०२६', '2026-10-15'), ('12/25/2026', '2026-12-25')]:
            self.check(text, iso)

    def test_relative_and_spoken(self):
        self.check('kal', '2026-10-10', amb=True)
        self.check('3 din baad', '2026-10-12')
        self.check('next Friday', '2026-10-16', amb=True)
        self.check('day after tomorrow', '2026-10-11')

    def test_day_first_and_read_back(self):
        self.check('05-06-2026', '2026-06-05', amb=True)
        self.assertEqual(dt.parse_date('15-10-2026', T).display, '15 Oct 2026 (Thu)')

    def test_times(self):
        for text, want in {'6:30 pm': ('18:30', None), '10am-12pm': ('10:00', '12:00'), '08:00am - 10:00am': ('08:00', '10:00'),
                           '4-6pm': ('16:00', '18:00'), 'shaam 6 baje': ('18:00', None)}.items():
            r = dt.parse_time(text)
            self.assertEqual((r['start'], r['end']), want, text)
        self.assertTrue(dt.parse_time('10:00')['ambiguous'])


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flags = [{'entity': 'artist', 'name': 'Ravi Shankar', 'art_form': 'Sitar', 'flag': 'deceased'}]
        cls.idx = DirectoryIndex(lambda: A, lambda: I, flags_provider=lambda: flags)

    def best(self, q, af=None):
        r = self.idx.search_artists(q, af)
        return r['best']['name'] if r['best'] else None

    def best_inst(self, q, city=None):
        r = self.idx.search_institutions(q, city=city)
        return r['best']['institution_name'] if r['best'] else None

    def test_spelling_variants_and_titles(self):
        self.assertEqual(self.best('Pt Ronu Mazumdar'), 'Ronu Majumdar')
        self.assertEqual(self.best('Shahid Pervez'), 'Ustad Shahid Parvez Khan')
        self.assertEqual(self.best('Faiyaz Dagar'), 'Padma Shri Ustad Faiyaz Wasifuddin Dagar')

    def test_indian_scripts(self):
        self.assertEqual(self.best('रोनू मजूमदार'), 'Ronu Majumdar')
        self.assertEqual(self.best('अजीत पाठक'), 'Ajeet Pathak')

    def test_deceased_and_similar_names_dc3(self):
        r = self.idx.search_artists('Pandit Ravi Shankar')
        self.assertIsNone(r['best'])
        self.assertTrue(r['ambiguous'])
        self.assertIn('deceased', r['matches'][0]['flags'])
        self.assertEqual(self.best('Ravi Shankar', 'Tabla'), 'Ravi Shankar Mishra')

    def test_several_art_forms_dc10(self):
        self.assertEqual(self.idx.search_artists('Ashwini Bhide')['matches'][0]['art_forms'], ['Vocal', 'Harmonium'])

    def test_institution_abbreviations(self):
        for q, want in [('IIT Bombay', 'Indian Institute of Technology Bombay'), ('IITB', 'Indian Institute of Technology Bombay'),
                        ('DPS Nashik', 'Delhi Public School'), ('St. Xavier’s College, Mumbai', "St Xavier's College"),
                        ('KV 2 Colaba', 'Kendriya Vidyalaya No. 2')]:
            self.assertEqual(self.best_inst(q), want, q)

    def test_campuses_dc4(self):
        r = self.idx.search_institutions('BITS Pilani')
        self.assertIsNone(r['best'])
        self.assertEqual({m['city'] for m in r['campus_choices']}, {'Pilani', 'Goa', 'Hyderabad'})
        self.assertEqual(self.best_inst('BITS Pilani', city='Goa'), 'BITS Pilani Goa Campus')


class MoneyTests(unittest.TestCase):
    def test_indian_grouping_and_words(self):
        self.assertEqual(tu.inr(675000), '6,75,000')
        self.assertEqual(tu.inr('1,23,45,678'), '1,23,45,678')
        self.assertEqual(tu.amount_in_words(6000), 'Rupees Six Thousand Only')
        self.assertEqual(tu.amount_in_words(2250000), 'Rupees Twenty Two Lakh Fifty Thousand Only')
        self.assertEqual(tu.mask_account('10773571902'), 'XXXXXXX1902')


class GovernanceAndRenderingTests(unittest.TestCase):
    def setUp(self):
        self.gov = Governance(os.path.join(tempfile.mkdtemp(), 'g.db'))
        self.gov.seed_templates(DEFAULT_TEMPLATES)
        self.r = TemplateRenderer(self.gov)
        self.org = org_context(self.gov.get_setting)

    def test_versions_and_rollback(self):
        v = self.gov.save_template('email.payment_request', 'NEW', subject='S', actor='t')
        self.assertEqual((v, self.gov.get_template('email.payment_request')['body']), (2, 'NEW'))
        self.gov.activate_template('email.payment_request', 1, 't')
        self.assertEqual(self.gov.get_template('email.payment_request')['version'], 1)
        self.assertTrue(any(a['action'] == 'template.activated' for a in self.gov.list_audit()))

    def test_sandbox_and_syntax_errors(self):
        self.assertFalse(self.r.validate("{{ ''.__class__.__mro__[1].__subclasses__() }}", ctx={})['ok'])
        bad = self.r.validate('{% if %}', ctx={})
        self.assertFalse(bad['ok'])
        self.assertEqual(bad['line'], 1)

    def test_every_email_renders(self):
        for key, t in DEFAULT_TEMPLATES.items():
            if t['kind'] == 'email':
                msg = self.r.render_email(key, sample_context(self.org))
                self.assertTrue(msg['subject'] and 'SPIC MACAY' in msg['html'] and msg['text'], key)

    def test_documents_survive_any_characters(self):
        pdf = PdfRenderer(self.r.text)
        ctx = sample_context(self.org, 'circuit')
        ctx['events'][0]['institution'] = "St. Xavier’s College — Fort\nContact: Fr. D’Souza – 98200"
        ctx['artists'].append({'role': 'Accompanying', 'name': 'Kalpesh Sāchala', 'art_form': 'Flute', 'phone': '', 'details': '₹ advance'})
        for v in ('single', 'circuit', 'virasat'):
            self.assertTrue(pdf.render_apr(self.r.layout(f'layout.apr.{v}'), ctx).startswith(b'%PDF'), v)
        rctx = dict(ctx, invoice_date='15 Oct 2026', line_items=[{'sl': 1, 'description': 'Concert', 'date': '16 Feb 2026', 'amount': 'Rs 10,000'}])
        self.assertTrue(pdf.render_rfp(self.r.layout('layout.rfp'), rctx).startswith(b'%PDF'))


if __name__ == '__main__':
    unittest.main()
