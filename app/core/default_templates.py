"""
Default wording and layouts. These seed the governance store on first run; after that,
administrators edit them in Admin > Templates (every save is a new, reversible version).
The wording of the Request for Payment, guidelines and thank-you emails is carried over
from the previous app so nothing already approved changes.
"""
import copy

SHELL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{margin:0;background:#f4ece2;font-family:Arial,Helvetica,sans-serif;color:#2a1b14;line-height:1.55}
.wrap{max-width:640px;margin:0 auto;padding:18px}
.head{background:#a3161e;color:#fff;padding:22px 26px;border-radius:12px 12px 0 0;border-bottom:4px solid #e9a800}
.head h1{margin:0;font-family:Georgia,serif;font-size:22px}
.head p{margin:4px 0 0;font-size:12px;opacity:.9}
.body{background:#fff;padding:26px;border-radius:0 0 12px 12px}
table.facts{width:100%;border-collapse:collapse;margin:16px 0;font-size:14px}
table.facts td{padding:8px 6px;border-bottom:1px solid #f0e3cf;vertical-align:top}
table.facts td.k{color:#6e0b14;font-weight:bold;width:38%}
table.grid{width:100%;border-collapse:collapse;font-size:13px;margin:12px 0}
table.grid th{background:#fff1cc;color:#6e0b14;text-align:left;padding:7px;border:1px solid #f0e3cf}
table.grid td{padding:7px;border:1px solid #f0e3cf;vertical-align:top}
.amount{background:#fff1cc;border:1px solid #e9a800;border-radius:10px;padding:14px;text-align:center;margin:18px 0}
.amount span{display:block;font-size:12px;color:#6e0b14}
.amount b{display:block;font-size:26px;color:#a3161e}
.sop h3{color:#6e0b14;font-size:15px;margin:18px 0 6px}
.sop ul{margin:0 0 6px 18px;padding:0}
.note{font-size:13px;color:#6b5a50}
.foot{text-align:center;font-size:12px;color:#8a7366;padding:14px}
a{color:#a3161e}
</style></head><body><div class="wrap">
<div class="head"><h1>{{ org.name }}</h1><p>{{ org.tagline }}</p></div>
<div class="body">{% block content %}{% endblock %}</div>
<div class="foot">{% block footer %}{{ org.name }} | <a href="{{ org.website }}">{{ org.website_short }}</a> | {{ org.info_email }}{% endblock %}</div>
</div></body></html>"""

SIGN = """<p style="margin-top:22px">Warm regards,<br><strong>{{ coordinator.name or org.name + ' Team' }}</strong><br>{{ org.name }}{% if coordinator.chapter %} {{ coordinator.chapter }}{% endif %}</p>"""

APR_CONFIRMATION = """{% extends "email.shell" %}{% block content %}
<p>Dear {{ coordinator.name or 'Coordinator' }},</p>
<p>The Artist Payment Request for this program has been filed. The APR document is attached{% if has_poster %}, along with the poster{% endif %}.</p>
<table class="facts">
<tr><td class="k">APR number</td><td>{{ apr.number }}</td></tr>
<tr><td class="k">Program</td><td>{{ program.type_label }}{% if program.title %}: {{ program.title }}{% endif %}</td></tr>
<tr><td class="k">Artists</td><td>{% for a in artists %}{{ a.name }}{% if a.art_form %} ({{ a.art_form }}){% endif %}{% if a.role != 'Main' %}, {{ a.role|lower }}{% endif %}{% if not loop.last %}<br>{% endif %}{% endfor %}</td></tr>
<tr><td class="k">Coordinators</td><td>{% for c in coordinators %}{{ c.name }}{% if c.email %} ({{ c.email }}){% endif %}{% if not loop.last %}<br>{% endif %}{% endfor %}</td></tr>
</table>
<table class="grid"><tr><th>Date</th><th>Time</th><th>Module</th><th>Institution</th></tr>
{% for e in events %}<tr><td>{{ e.date }}</td><td>{{ e.time or '-' }}</td><td>{{ e.module }}</td><td>{{ e.institution_line }}</td></tr>{% endfor %}
</table>
{% if program.notes %}<p class="note"><b>Notes:</b> {{ program.notes }}</p>{% endif %}
<p class="note">Filed through the {{ org.name }} APR Assistant.</p>
{% endblock %}"""

PAYMENT_REQUEST = """{% extends "email.shell" %}{% block content %}
<p>{% if institution.contact_name %}Dear {{ institution.contact_name }},{% else %}Dear Sir/Madam,{% endif %}</p>
<p>Greetings from {{ org.name }}!</p>
<p>Thank you for partnering with us to host this programme under the {{ org.name }} movement. We hope the students and faculty enjoyed the session and that it opened a door to India's rich cultural heritage for them.</p>
{% if feedback_url %}<p>We would love to hear how it went. If you can spare a few minutes, your feedback genuinely shapes how we plan future programmes: <a href="{{ feedback_url }}">share your feedback</a>.</p>{% endif %}
<table class="facts">
<tr><td class="k">Institute</td><td>{{ institution.name }}</td></tr>
{% for e in events %}<tr><td class="k">{{ e.date }}</td><td>{{ e.module }}{% if e.artists_text %} by {{ e.artists_text }}{% endif %}</td></tr>{% endfor %}
{% if reference %}<tr><td class="k">Reference</td><td>{{ reference }}</td></tr>{% endif %}
</table>
<div class="amount"><span>Contribution towards the programme</span><b>&#8377;{{ amount_inr }}</b><span>{{ amount_words }}</span></div>
<p>For your records, we have enclosed the details of the contribution towards the programme, along with our bank particulars, should your office wish to process it at its convenience. Contributions from host institutions are what allow us to take artists to more schools and colleges across the country.</p>
<p>If this has already been arranged, please do treat this note simply as an acknowledgement, with our thanks.</p>
<p>For anything at all, we are reachable at {{ org.info_email }}.</p>
""" + SIGN + "{% endblock %}"

PAYMENT_REQUEST_TEXT = """{% if institution.contact_name %}Dear {{ institution.contact_name }},{% else %}Dear Sir/Madam,{% endif %}

Greetings from {{ org.name }}!

Thank you for partnering with us to host this programme under the {{ org.name }} movement. We hope the students and faculty enjoyed the session and that it opened a door to India's rich cultural heritage for them.
{% if feedback_url %}
We would love to hear how it went: {{ feedback_url }}
{% endif %}
Contribution towards the programme: Rs {{ amount_inr }} ({{ amount_words }}). The details and our bank particulars are attached.

If this has already been arranged, please treat this note simply as an acknowledgement, with our thanks.

For anything at all, we are reachable at {{ org.info_email }}.

Warm regards,
{{ coordinator.name or org.name + ' Team' }}
{{ org.name }}
{{ org.website_short }}"""

GUIDELINES = """{% extends "email.shell" %}{% block content %}
<p>{% if institution.contact_name %}Dear {{ institution.contact_name }},{% else %}Dear Sir/Madam,{% endif %}</p>
<p>Greetings from {{ org.name }}! We are delighted to confirm the following {% if events|length > 1 %}programmes{% else %}programme{% endif %} at {{ institution.name }}.</p>
<table class="grid"><tr><th>Date</th><th>Time</th><th>Programme</th><th>Artists</th></tr>
{% for e in events %}<tr><td>{{ e.date }}</td><td>{{ e.time or 'To be confirmed' }}</td><td>{{ e.module }}</td><td>{{ e.artists_text }}</td></tr>{% endfor %}
</table>
<p>To help the session run beautifully, here is a short summary of what we request from the host institution.</p>
<div class="sop">
<h3>Travel</h3><ul><li>Please arrange a well-maintained vehicle to bring the artistes from their place of stay to the venue, and to drop them back.</li><li>Senior students and/or faculty should escort the artistes.</li><li>Kindly ensure the artistes reach the venue one hour before the scheduled start.</li></ul>
<h3>Green room</h3><ul><li>A clean, private green room near the auditorium, preferably with an attached toilet and curtained windows.</li><li>Floor seating (darees or carpets covered with white sheets), plus a table and three or four chairs to the side.</li><li>Drinking water and glasses. The room should be lockable so instruments can be left safely.</li></ul>
<h3>Stage and sound</h3><ul><li>An appropriate stage, with no cloth or carpet covering it. It may be decorated with flowers, rangoli and diyas.</li><li>Only the {{ org.name }} third-eye logo on the backdrop, with no other banners or posters on stage or in the auditorium.</li><li>Sound system provided by the institution. Typical requirement: tabla 1 mike, vocal and harmonium 2 mikes, sitar 1 mike, announcements 2 stand mikes, dance 2 high-quality foot mikes. Full, normal stage lighting and four bottles of mineral water.</li><li>Baithak-style seating in a closed auditorium is ideal, with students seated close to the artistes.</li></ul>
<h3>During the programme</h3><ul><li>Starting on time is crucial. The programme may open with lamp lighting by the head of the institution along with the artiste.</li><li>The compere should have the artiste's bio-data, reconfirmed with them beforehand, and should check the correct sequence for introducing and felicitating the artistes.</li><li>Mobile phones switched off, minimal movement, and no flash photography. Any photography or video needs the artistes' prior consent.</li><li>A 15-minute interactive question-and-answer session closes the programme, followed by felicitation of all artistes and a vote of thanks.</li></ul>
<h3>Hospitality and acknowledgement</h3><ul><li>Light refreshments before and/or after the concert, and breakfast or lunch for the artistes as appropriate. Students serving the artistes themselves adds a lovely touch.</li><li>Bottled water and glasses on or near the stage during the programme.</li><li>Afterwards, a Letter of Acknowledgement on institution letterhead, signed by the head of the institution, to be handed to the {{ org.name }} volunteer.</li></ul>
</div>
{% if has_attachment %}<p class="note">The complete guidelines are attached as a PDF.</p>{% endif %}
<p>Please do reach out if anything above needs discussion; we are glad to help.</p>
""" + SIGN + "{% endblock %}"

ARTIST_ACK = """{% extends "email.shell" %}{% block content %}
<p>Dear {{ artist.name }},</p>
<p>Thank you for performing for {{ org.name }} at {{ event.institution }}. Sharing your art with students is what this movement exists for, and we are grateful you gave your time and music to them.</p>
<table class="facts">
<tr><td class="k">Programme</td><td>{{ event.module }}</td></tr>
<tr><td class="k">Institution</td><td>{{ event.institution }}</td></tr>
<tr><td class="k">Date</td><td>{{ event.date }}</td></tr>
<tr><td class="k">Reference</td><td>{{ reference }}</td></tr>
</table>
<p>Your payment request has been raised with our office and is now being processed. We will write to you again as soon as the payment has been released; there is nothing you need to do in the meantime.</p>
{% if feedback_url %}<p>If you have a few minutes, we would love to hear how the session went from your side: <a href="{{ feedback_url }}">share your feedback</a>.</p>{% else %}<p>If you have a few minutes, we would love to hear how the session went from your side; simply reply to this email.</p>{% endif %}
<p>We hope to have the pleasure of hosting you again soon.</p>
""" + SIGN + "{% endblock %}"

ACG_NEW_ARTIST = """{% extends "email.shell" %}{% block content %}
<p>Dear Artist Care Group,</p>
<p>{{ coordinator.name or 'A coordinator' }} added a new artist through the APR Assistant. The record has been saved <b>provisionally</b> so the program could go ahead, and is waiting for your review.</p>
<table class="facts">
<tr><td class="k">Name</td><td>{{ artist.name }}</td></tr>
<tr><td class="k">Art form</td><td>{{ artist.art_form }}</td></tr>
<tr><td class="k">Added as</td><td>{{ artist.role }} artist</td></tr>
<tr><td class="k">City / State</td><td>{{ artist.city }}{% if artist.state %}, {{ artist.state }}{% endif %}</td></tr>
<tr><td class="k">Contact</td><td>{{ artist.email or '-' }} | {{ artist.phone or '-' }}</td></tr>
<tr><td class="k">Program</td><td>{{ program_summary }}</td></tr>
</table>
<p>Approve or reject it in the Admin console: <a href="{{ admin_url }}">{{ admin_url }}</a></p>
{% endblock %}"""

COORDINATOR_REQUEST = """{% extends "email.shell" %}{% block content %}
<p>Hello,</p>
<p>{{ coordinator.name or 'A coordinator' }} asked to add a co-coordinator who is not in the coordinator directory.</p>
<table class="facts">
<tr><td class="k">Name</td><td>{{ requested.name or '-' }}</td></tr>
<tr><td class="k">Email</td><td>{{ requested.email or '-' }}</td></tr>
<tr><td class="k">Phone</td><td>{{ requested.phone or '-' }}</td></tr>
<tr><td class="k">Chapter</td><td>{{ requested.chapter or '-' }}</td></tr>
<tr><td class="k">Program</td><td>{{ program_summary }}</td></tr>
</table>
<p>Review the request in the Admin console: <a href="{{ admin_url }}">{{ admin_url }}</a></p>
{% endblock %}"""

LOGIN_CODE = """{% extends "email.shell" %}{% block content %}
<p>Your sign-in code for the {{ org.name }} APR Assistant is:</p>
<p style="font-size:30px;font-weight:bold;letter-spacing:6px;color:#a3161e">{{ code }}</p>
<p class="note">It expires in {{ minutes }} minutes. If you didn't ask for it, you can ignore this email.</p>
{% endblock %}"""

APR_BATCH = """{% extends "email.shell" %}{% block content %}
<p>Dear {{ coordinator.name or 'Coordinator' }},</p>
<p>{{ aprs|length }} Artist Payment Request{{ 's' if aprs|length != 1 else '' }} {{ 'were' if aprs|length != 1 else 'was' }} filed together through the APR Assistant. The APR documents are attached.</p>
<table class="grid"><tr><th>APR</th><th>Program</th><th>Dates</th><th>Institutions</th></tr>
{% for a in aprs %}<tr><td>{{ a.number }}</td><td>{{ a.program }}</td><td>{{ a.dates }}</td><td>{{ a.institutions }}</td></tr>{% endfor %}
</table>
{% if pending %}<p class="note">Still to file: {{ pending }}.</p>{% endif %}
<p class="note">Filed through the {{ org.name }} APR Assistant.</p>
{% endblock %}"""

HOUSE_RULES = """- Many coordinators are volunteers; be respectful, patient and brief.
- Say "program" for the whole booking and "event" for each session within it.
- Keep each reply short enough to read on a phone screen.
- When something is optional (photos, bank details, accompanying artists), mention it once and move on."""


def _cols(*specs):
    return [{'key': k, 'label': l, 'width': w, 'enabled': e} for k, l, w, e in specs]


def apr_layout(variant: str) -> dict:
    return {
        'page': {'orientation': 'landscape', 'margin_mm': 12},
        'style': {'accent': '#8B0000', 'header_fill': '#F2F2F2', 'grid': '#BDBDBD', 'font_size': 8.6},
        'date_format': '%d-%b-%Y', 'time_format': '12h',
        'header': {'show_logo': True, 'title': 'Artist Payment Request  |  APR No: {{ apr.number }}',
                   'subtitle': '{% if program.title and program.title.lower().startswith(program.type_label.lower()) %}{{ program.title }}'
                               '{% else %}{{ program.type_label }}{% if program.title %}: {{ program.title }}{% endif %}{% endif %}'},
        'sections': [
            {'id': 'coordinators', 'type': 'table', 'title': 'Coordinators', 'enabled': True, 'source': 'coordinators',
             'columns': _cols(('name', 'Name', 30, True), ('chapter', 'Chapter', 20, True), ('phone', 'Mobile No', 20, True), ('email', 'Email', 30, True))},
            {'id': 'events', 'type': 'table', 'title': 'Events', 'enabled': True, 'source': 'events',
             'columns': _cols(('sl', 'Sl.', 4, True), ('date', 'Date', 9, True), ('time', 'Time', 12, True),
                              ('module', 'Module', 13, True), ('artists', 'Artist', 15, variant == 'virasat'),
                              ('institution', 'Institution', 21 if variant == 'virasat' else 25, True),
                              ('audience_students', 'Audience (Student)', 8, True), ('audience_other', 'Audience (Other)', 8, True),
                              ('contribution', 'Contribution', 10, True))},
            {'id': 'artists', 'type': 'table', 'title': 'Artists', 'enabled': True, 'source': 'artists',
             'columns': _cols(('role', 'Role', 16, True), ('name', 'Name', 30, True), ('art_form', 'Artform', 20, True),
                              ('phone', 'Mobile No', 14, True), ('details', 'Additional Details', 20, True))},
            {'id': 'summary', 'type': 'lines', 'title': '', 'enabled': True,
             'lines': ['No of Events: {{ totals.events }}',
                       'Total Contribution: {% if totals.contribution_inr %}Rs {{ totals.contribution_inr }}{% else %}-{% endif %}',
                       'Total Receipts: Rs', 'Total Expenditure: Rs',
                       'Payment Required by Delhi A/c: {{ "Yes" if program.payment_required else "No" }}']},
            {'id': 'notes', 'type': 'notes', 'title': 'Additional notes', 'enabled': True},
        ],
        'footer': {'left': 'Generated on {{ generated_at }}', 'center': '{{ page }}/{{ pages }}', 'right': '{{ org.website_short }}'},
    }


RFP_LAYOUT = {
    'page': {'orientation': 'portrait', 'margin_mm': 18},
    'style': {'accent': '#8B0000', 'header_fill': '#F2F2F2', 'grid': '#9E9E9E', 'font_size': 10},
    'date_format': '%d %b %Y',
    'header': {'show_logo': True, 'title': 'Request for payment', 'invoice_label': 'INV DATE:'},
    'to_label': 'TO,',
    'description': '{% if program.title %}{{ program.title }} - {% endif %}{{ e.art_form }} {{ e.module|lower }} of {{ e.artists_text }}',
    'columns': _cols(('sl', 'S.No', 8, True), ('description', 'Description - Contribution towards', 52, True),
                     ('date', 'Date of event', 20, True), ('amount', 'Total amount', 20, True)),
    'after_table': ['Total (in Rupees): Rs {{ amount_inr }}', 'Amount in words: {{ amount_words }}',
                    'Cheque/NEFT may please be made in favour of "{{ bank.account_name }}"'],
    'bank_block': ['Kindly arrange the payment by NEFT/Bank transfer to our', 'Current Account: {{ bank.bank_name }} ({{ bank.branch }})',
                   'A/c Name: {{ bank.account_name }}', 'A/c No: {{ bank.account_number }}', 'IFSC: {{ bank.ifsc }}',
                   'PAN: {{ org.pan }}    TAN: {{ org.tan }}', 'Registered office: {{ org.registered_office }}'],
    'signature': ['({{ signatory.name }})', '{{ signatory.title }},', '{{ org.name }}'],
    'footer': {'left': '', 'center': '{{ org.name }} | {{ org.website_short }} | {{ org.info_email }}', 'right': '{{ page }}/{{ pages }}'},
}

POSTER_STYLE = {
    'tagline': 'Society for the Promotion of Indian Classical Music And Culture Amongst Youth',
    'footer_tagline': 'Have every child experience the inspiration and mysticism in Indian and World Heritage',
    'info_line': 'For more info visit us at www.spicmacay.org',
    'presenter_template': '{chapter_or_institution} PRESENTS',
    'show_coordinator': True, 'show_accompanying': True,
}


def _email(title, subject, body, placeholders, text=None):
    meta = {'placeholders': placeholders}
    if text:
        meta['text'] = text
    return {'kind': 'email', 'title': title, 'subject': subject, 'body': body, 'meta': meta}


DEFAULT_TEMPLATES = {
    'email.shell': {'kind': 'email_layout', 'title': 'Email frame (header and footer)', 'subject': None, 'body': SHELL,
                    'meta': {'placeholders': ['org.name', 'org.tagline', 'org.website', 'org.website_short', 'org.info_email']}},
    'email.apr_confirmation': _email('APR filed (to coordinators and finance)', 'APR {{ apr.number }} filed: {{ program.title or events[0].institution }}',
                                     APR_CONFIRMATION, ['coordinator.name', 'apr.number', 'program.type_label', 'program.title', 'program.notes', 'artists', 'events', 'coordinators']),
    'email.payment_request': _email('Request for Payment (to the institution)',
                                    'Thank You — Programme Feedback & Contribution Details – {{ org.name }} ({{ institution.name }})',
                                    PAYMENT_REQUEST, ['institution.name', 'institution.contact_name', 'events', 'amount_inr', 'amount_words', 'reference', 'feedback_url', 'coordinator.name'],
                                    text=PAYMENT_REQUEST_TEXT),
    'email.pre_event_guidelines': _email('Pre-event guidelines (to the institution)',
                                         '{{ org.name }} Programme Confirmation & Pre-Event Guidelines — {{ institution.name }}',
                                         GUIDELINES, ['institution.name', 'institution.contact_name', 'events', 'has_attachment', 'coordinator.name']),
    'email.artist_acknowledgement': _email('Thank-you to the artist', 'Thank You for Your Programme — {{ org.name }}', ARTIST_ACK,
                                           ['artist.name', 'event.module', 'event.institution', 'event.date', 'reference', 'feedback_url']),
    'email.acg_new_artist': _email('New provisional artist (to Artist Care Group)', 'New provisional artist for review: {{ artist.name }} ({{ artist.art_form }})',
                                   ACG_NEW_ARTIST, ['artist.name', 'artist.art_form', 'artist.role', 'artist.city', 'program_summary', 'admin_url']),
    'email.coordinator_request': _email('Coordinator addition request (to admins)', 'Request to add a coordinator: {{ requested.name or requested.email }}',
                                        COORDINATOR_REQUEST, ['requested.name', 'requested.email', 'program_summary', 'admin_url']),
    'email.apr_batch_summary': _email('Several APRs filed together (to coordinators)', '{{ aprs|length }} APRs filed: {{ aprs[0].program }}{% if aprs|length > 1 %} and {{ aprs|length - 1 }} more{% endif %}',
                                      APR_BATCH, ['coordinator.name', 'aprs', 'pending']),
    'email.login_code': _email('Sign-in code', 'Your {{ org.name }} APR Assistant sign-in code', LOGIN_CODE, ['code', 'minutes']),
    'layout.apr.single': {'kind': 'apr_layout', 'title': 'APR layout: single program', 'body': None, 'meta': {}},
    'layout.apr.circuit': {'kind': 'apr_layout', 'title': 'APR layout: circuit', 'body': None, 'meta': {}},
    'layout.apr.virasat': {'kind': 'apr_layout', 'title': 'APR layout: Virasat', 'body': None, 'meta': {}},
    'layout.rfp': {'kind': 'rfp_layout', 'title': 'Request for Payment document', 'body': None, 'meta': {}},
    'layout.poster': {'kind': 'poster_style', 'title': 'Poster wording and options', 'body': None, 'meta': {}},
    'prompt.house_rules': {'kind': 'prompt', 'title': 'Assistant house rules', 'subject': None, 'body': HOUSE_RULES,
                           'meta': {'help': 'Plain-language rules the assistant always follows. Safety rules (confirm before emailing or filing) are built in and cannot be switched off here.'}},
}
import json as _json
for _v in ('single', 'circuit', 'virasat'):
    DEFAULT_TEMPLATES[f'layout.apr.{_v}']['body'] = _json.dumps(apr_layout(_v), indent=2)
DEFAULT_TEMPLATES['layout.rfp']['body'] = _json.dumps(RFP_LAYOUT, indent=2)
DEFAULT_TEMPLATES['layout.poster']['body'] = _json.dumps(POSTER_STYLE, indent=2)

# Well-known artists who have passed away (reviewer comment DC3). Matching also checks the
# art form, so a living namesake in a different art form is not flagged. Editable in
# Admin > Directory flags; the Artist Care Group should own this list.
DEFAULT_FLAGS = [
    {'name': n, 'art_form': a, 'flag': 'deceased', 'note': f'Passed away in {y}'} for n, a, y in [
        ('Ravi Shankar', 'Sitar', 2012), ('Bismillah Khan', 'Shehnai', 2006), ('Bhimsen Joshi', 'Vocal', 2011),
        ('M S Subbulakshmi', 'Vocal', 2004), ('Kishan Maharaj', 'Tabla', 2008), ('Ali Akbar Khan', 'Sarod', 2009),
        ('Jasraj', 'Vocal', 2020), ('Shivkumar Sharma', 'Santoor', 2022), ('Zakir Hussain', 'Tabla', 2024),
        ('Birju Maharaj', 'Kathak', 2022), ('Girija Devi', 'Vocal', 2017), ('Kishori Amonkar', 'Vocal', 2017),
        ('Vilayat Khan', 'Sitar', 2004), ('Rajan Mishra', 'Vocal', 2021), ('Rashid Khan', 'Vocal', 2024),
        ('Kelucharan Mohapatra', 'Odissi', 2004), ('Lalgudi Jayaraman', 'Violin', 2013),
        ('M Balamuralikrishna', 'Vocal', 2016), ('U Srinivas', 'Mandolin', 2014), ('Gangubai Hangal', 'Vocal', 2009),
        ('Kumar Gandharva', 'Vocal', 1992), ('Mallikarjun Mansur', 'Vocal', 1992), ('Alla Rakha', 'Tabla', 2000),
        ('Nikhil Banerjee', 'Sitar', 1986), ('Asad Ali Khan', 'Rudra Veena', 2011), ('Ram Narayan', 'Sarangi', 2024),
        ('Sultan Khan', 'Sarangi', 2011), ('Debu Chaudhuri', 'Sitar', 2021), ('Sitara Devi', 'Kathak', 2014),
        ('Zia Fariduddin Dagar', 'Dhrupad', 2013), ('Rahim Fahimuddin Dagar', 'Dhrupad', 2011),
    ]
]

_SAMPLE_EVENTS = [
    {'sl': 1, 'date': '14-Feb-2026', 'time': '8:00 am - 10:00 am', 'module': 'Lecture Demonstration', 'artists': 'Ronu Majumdar',
     'institution': 'APS Ahmednagar, Ahmednagar, Maharashtra\nContact Details: Principal - 98200 00000', 'institution_line': 'APS Ahmednagar, Ahmednagar',
     'audience_students': '400', 'audience_other': '', 'contribution': '23,000', 'artists_text': 'Pt. Ronu Majumdar with Ajeet Pathak',
     'art_form': 'Flute', 'city': 'Ahmednagar'},
    {'sl': 2, 'date': '16-Feb-2026', 'time': '10:00 am - 12:00 pm', 'module': 'Lecture Demonstration', 'artists': 'Ronu Majumdar',
     'institution': 'DPS Nashik, Nashik, Maharashtra', 'institution_line': 'DPS Nashik, Nashik', 'audience_students': '500',
     'audience_other': '', 'contribution': '10,000', 'artists_text': 'Pt. Ronu Majumdar with Ajeet Pathak', 'art_form': 'Flute', 'city': 'Nashik'},
]


def sample_context(org: dict, kind: str = 'circuit') -> dict:
    """Realistic data for previews in the Admin console (modelled on APR 1777)."""
    events = copy.deepcopy(_SAMPLE_EVENTS)
    return {
        'org': org, 'coordinator': {'name': 'Sabyasachi', 'email': 'sabyasachi@spicmacay.com', 'phone': '81080 98246', 'chapter': 'Mumbai'},
        'apr': {'number': '1777', 'request_id': 'REQ-20260224-1A2B3C'},
        'program': {'type': kind, 'type_label': {'single': 'Single Event', 'circuit': 'Circuit', 'virasat': 'Virasat'}.get(kind, 'Circuit'),
                    'title': 'Maharashtra Circuit', 'notes': 'School payments to be made directly into the SPIC MACAY Delhi account.',
                    'payment_required': True},
        'coordinators': [{'name': 'Sabyasachi', 'chapter': 'Mumbai', 'phone': '81080 98246', 'email': 'sabyasachi@spicmacay.com'},
                         {'name': 'Banashree Roy', 'chapter': 'Guwahati', 'phone': '', 'email': ''}],
        'artists': [{'role': 'Main', 'name': 'Ronu Majumdar', 'art_form': 'Flute', 'phone': '98203 20131', 'details': ''},
                    {'role': 'Accompanying', 'name': 'Ajeet Pathak', 'art_form': 'Tabla', 'phone': '', 'details': ''}],
        'events': events if kind != 'single' else events[:1],
        'totals': {'events': len(events) if kind != 'single' else 1, 'contribution_inr': '33,000'},
        'generated_at': '24-Feb-2026 03:54pm',
        'institution': {'name': 'DPS Nashik', 'contact_name': 'Mrs. Kulkarni', 'email': 'principal@dpsnashik.in', 'city': 'Nashik'},
        'amount': 10000, 'amount_inr': '10,000', 'amount_words': 'Rupees Ten Thousand Only', 'reference': 'APR 1777',
        'feedback_url': '', 'has_attachment': True, 'has_poster': True,
        'artist': {'name': 'Ronu Majumdar', 'art_form': 'Flute', 'role': 'Main', 'city': 'Mumbai', 'state': 'Maharashtra',
                   'email': 'artist@example.com', 'phone': ''},
        'event': {'module': 'Lecture Demonstration', 'institution': 'DPS Nashik', 'date': '16 Feb 2026'},
        'requested': {'name': 'Banashree Roy', 'email': 'banashree@example.com', 'phone': '', 'chapter': 'Guwahati'},
        'program_summary': 'Circuit, 2 events, Ronu Majumdar (Flute)', 'admin_url': 'https://example.org/admin',
        'code': '482913', 'minutes': 10, 'pending': '',
        'aprs': [{'number': '1777', 'program': 'Circuit: Ronu Majumdar', 'dates': '14 to 16 Feb 2026', 'institutions': 'APS Ahmednagar, DPS Nashik'},
                 {'number': '1778', 'program': 'Virasat 2026, Nalanda Public School', 'dates': '9 to 11 Sep 2026', 'institutions': 'Nalanda Public School'}],
        'bank': {'bank_name': 'State Bank of India', 'branch': 'Modern School, Barakhamba Road, New Delhi', 'account_name': 'SPIC MACAY',
                 'account_number': '10773571902', 'ifsc': 'SBIN0011781'},
        'signatory': {'name': 'Sabyasachi Dey', 'title': 'National Coordinator'},
    }
