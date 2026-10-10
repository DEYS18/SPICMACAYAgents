"""
Default wording and layouts. These seed the governance store on first run; after that,
administrators edit them in Admin > Templates (every save is a new, reversible version).
The wording of the Request for Payment, guidelines and thank-you emails is carried over
from the previous app so nothing already approved changes.
"""
import copy

# The look of the previous app's emails, which coordinators liked: a haldi-gold banner with a sindoor rule, a warm
# cream page, a pill naming what the email is about, white fact cards edged in red and a gold amount box. The APR
# confirmation keeps its own sindoor banner. Layout uses tables, not flexbox, so Outlook and Gmail render it the same.
SHELL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only"><meta name="supported-color-schemes" content="light">
<style>
body{margin:0;padding:0;background:#F6EEDC;font-family:Arial,Helvetica,sans-serif;color:#3D2B00;line-height:1.6;-webkit-text-size-adjust:100%}
.wrap{max-width:620px;margin:0 auto;padding:20px 12px}
.head{background:#F7C948;background:linear-gradient(135deg,#FDEFB8 0%,#F7C948 55%,#E8A800 100%);color:#8B0000;padding:28px 24px 24px;text-align:center;border-radius:12px 12px 0 0;border-bottom:4px solid #B3161C}
.head h1{margin:0;font-family:Georgia,'Times New Roman',serif;font-size:24px;line-height:1.25;color:#8B0000}
.head p{margin:6px 0 0;font-size:12.5px;color:#7A2A12}
.head .rule{display:block;width:70px;height:2px;margin:12px auto 0;background:#B3161C;font-size:0;line-height:0}
.head.sindoor{background:#A3161E;background:linear-gradient(135deg,#8B0000 0%,#C1121F 60%,#DC143C 100%);border-bottom-color:#E8A800}
.head.sindoor h1,.head.sindoor p{color:#FFFFFF}
.head.sindoor .rule{background:#F7C948}
.body{background:#FFFBEF;padding:28px 26px 24px;border:1px solid #F1E2B8;border-top:0;border-radius:0 0 12px 12px}
.body p{margin:0 0 12px}
.pill{display:inline-block;background:#FFF3CD;border:2px solid #FFC107;color:#7A5B00;font-weight:bold;padding:5px 15px;border-radius:20px;font-size:13px;margin:2px 0 14px}
table.facts{width:100%;border-collapse:separate;border-spacing:0;background:#FFFFFF;border-left:4px solid #B3161C;border-radius:10px;margin:18px 0;font-size:14px}
table.facts th{text-align:left;color:#8B0000;font-size:15px;padding:12px 14px 2px;font-family:Georgia,'Times New Roman',serif}
table.facts td{padding:9px 14px;border-bottom:1px solid #F0E6C8;vertical-align:top}
table.facts tr:last-child td{border-bottom:0}
table.facts td.k{color:#8B0000;font-weight:bold;width:40%}
table.facts.plain{background:transparent;border-left:0;margin:0}
table.facts.plain td{padding:4px 0;border-bottom:0}
table.grid{width:100%;border-collapse:collapse;font-size:13px;margin:14px 0}
table.grid th{background:#5B1414;color:#FFFFFF;text-align:left;padding:8px 9px;font-size:12px}
table.grid td{padding:8px 9px;border-bottom:1px solid #F0E6C8;vertical-align:top;background:#FFFFFF}
table.grid tr:nth-child(even) td{background:#FFF6DF}
.apr-box{background:#FFF3CD;border:2px solid #FFC107;border-radius:10px;padding:10px 16px;margin:18px 0}
.apr-box .big{font-size:22px;color:#8B0000}
.amount{background:#F7C948;background:linear-gradient(135deg,#FDEFB8 0%,#F7C948 100%);border:2px solid #E8A800;border-radius:10px;padding:16px 20px;margin:20px 0;text-align:center}
.amount span{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#7A5B00;font-weight:bold}
.amount b{display:block;font-size:28px;color:#8B0000;margin-top:4px;line-height:1.2}
.amount small{display:block;font-size:12.5px;color:#7A5B00;margin-top:4px}
.bank{background:#FFFFFF;border:1px dashed #E8C66A;border-radius:10px;padding:10px 16px 8px;margin:16px 0}
.bank h3,.box h3{margin:0 0 6px;color:#8B0000;font-size:14px}
.attach{font-size:13px;color:#5C4630;background:#FFFFFF;border:1px dashed #E8C66A;border-radius:8px;padding:8px 12px;margin:16px 0}
.sop h3{color:#8B0000;font-size:15px;margin:18px 0 6px}
.sop ul{margin:0 0 6px 18px;padding:0}
.sop li{font-size:13.5px;margin-bottom:4px}
.note{font-size:13px;color:#7A6050}
.nw{white-space:nowrap}
.sign{margin-top:22px}
.foot{text-align:center;font-size:12px;color:#7A6050;padding:16px 10px 4px;line-height:1.7}
a{color:#B3161C}
</style></head><body><div class="wrap">
{% block banner %}<div class="head"><h1>&#127917; {{ org.name }}</h1><p>{{ org.tagline }}</p><span class="rule">&nbsp;</span></div>{% endblock %}
<div class="body">{% block content %}{% endblock %}</div>
<div class="foot">{% block footer %}This is an automated email from the {{ org.name }} Supatra Platform.<br><a href="{{ org.website }}">{{ org.website_short }}</a>{% if org.info_email %} &middot; {{ org.info_email }}{% endif %}<br>&copy; {{ year }} {{ org.name }}. All rights reserved.{% endblock %}</div>
</div></body></html>"""

SIGN = """<p class="sign">Warm regards,<br><strong>{{ coordinator.name or org.name + ' Team' }}</strong><br>{{ org.name }}{% if coordinator.chapter %} {{ coordinator.chapter }}{% endif %}</p>"""

APR_CONFIRMATION = """{% extends "email.shell" %}
{% block banner %}<div class="head sindoor"><h1>&#127917; {{ org.name }} Artist Payment Request (APR) Confirmation</h1><p>{{ org.tagline }}</p><span class="rule">&nbsp;</span></div>{% endblock %}
{% block content %}
<p>Namaste{% if coordinator.name %} {{ coordinator.name }} ji{% endif %},</p>
<span class="pill">&#9989; APR Filed</span>
<p>Your {{ org.name }} program has been registered and its Artist Payment Request (APR) has been created. The APR document is attached{% if has_poster %}, along with the program poster{% endif %}{% if has_calendar %} and a calendar invite{% endif %}.</p>
<div class="apr-box"><table class="facts plain">
<tr><td class="k">&#128203; APR No.</td><td><b class="big">{{ apr.number }}</b></td></tr>
{% if apr.request_id %}<tr><td class="k">Request ID</td><td>{{ apr.request_id }}</td></tr>{% endif %}
<tr><td class="k">Program</td><td>{{ program.type_label }}{% if program.title %}: {{ program.title }}{% endif %}</td></tr>
<tr><td class="k">Events</td><td>{{ events|length }}</td></tr>
</table></div>
<table class="facts">
<tr><th colspan="2">Program details</th></tr>
<tr><td class="k">Artists</td><td>{% for a in artists %}{{ a.name }}{% if a.art_form %} ({{ a.art_form }}){% endif %}{% if a.role not in ('Main', 'Performer') %}, {{ a.role|lower }}{% endif %}{% if not loop.last %}<br>{% endif %}{% endfor %}</td></tr>
{% if events|length == 1 %}{% set e = events[0] %}
<tr><td class="k">Date</td><td>{{ e.date }}</td></tr>
<tr><td class="k">Time</td><td>{{ e.time or 'To be confirmed' }}</td></tr>
<tr><td class="k">Module</td><td>{{ e.module }}</td></tr>
<tr><td class="k">Institution</td><td>{{ e.institution_line }}</td></tr>
<tr><td class="k">Expected students</td><td>{{ e.audience_students or '-' }}</td></tr>
{% endif %}
<tr><td class="k">Coordinators</td><td>{% for c in coordinators %}{{ c.name }}{% if c.email %} ({{ c.email }}){% endif %}{% if not loop.last %}<br>{% endif %}{% endfor %}</td></tr>
<tr><td class="k">Payment by Delhi A/c</td><td>{{ 'Yes' if program.payment_required else 'No' }}</td></tr>
</table>
{% if events|length > 1 %}<table class="grid"><tr><th>#</th><th>Date</th><th>Time</th><th>Module</th><th>Institution</th><th>Students</th><th>Contribution</th></tr>
{% for e in events %}<tr><td>{{ loop.index }}</td><td class="nw">{{ e.date }}</td><td>{{ e.time or '-' }}</td><td>{{ e.module }}{% if program.type == 'virasat' and e.artists %}<br><small>{{ e.artists }}</small>{% endif %}</td><td>{{ e.institution_line }}</td><td>{{ e.audience_students or '-' }}</td><td>{% if e.contribution and e.contribution != 'NIL' %}&#8377;{{ e.contribution }}{% else %}{{ e.contribution or '-' }}{% endif %}</td></tr>{% endfor %}
</table>{% endif %}
{% if totals.contribution_inr %}<div class="amount"><span>{% if events|length > 1 %}Total contribution from institutions{% else %}Contribution from the institution{% endif %}</span><b>&#8377;{{ totals.contribution_inr }}</b></div>{% endif %}
{% if program.notes %}<p class="note"><b>Notes:</b> {{ program.notes }}</p>{% endif %}
<p class="attach">&#128206; <b>Attached:</b> APR {{ apr.number }} (PDF){% if has_poster %} &middot; program poster{% endif %}{% if has_calendar %} &middot; calendar invite (.ics): open it to add the {{ 'events' if calendar_events > 1 else 'event' }} to your calendar{% endif %}</p>
<p>For any queries or changes, please contact the {{ org.name }} coordination team.</p>
<p>Thank you for promoting Indian classical arts and culture!</p>
<p class="sign"><strong>{{ org.name }} Team</strong><br><em>Spreading the essence of Indian heritage</em></p>
{% endblock %}"""

PAYMENT_REQUEST = """{% extends "email.shell" %}{% block content %}
<p>{% if institution.contact_name %}Dear {{ institution.contact_name }},{% else %}Dear Sir/Madam,{% endif %}</p>
<span class="pill">&#128591; With Our Thanks</span>
<p>Greetings from {{ org.name }}!</p>
<p>Thank you for partnering with us to host this programme under the {{ org.name }} movement. We hope the students and faculty enjoyed the session and that it opened a door to India's rich cultural heritage for them.</p>
{% if feedback_url %}<p>We would love to hear how it went. If you can spare a few minutes, your feedback genuinely shapes how we plan future programmes.</p>{% endif %}
<table class="facts">
<tr><td class="k">Institute Name</td><td>{{ institution.name }}</td></tr>
{% for e in events %}<tr><td class="k">{% if events|length > 1 %}Event {{ loop.index }}: {% endif %}Date / Type</td><td>{{ e.date }} / {{ e.module }}</td></tr>
{% if e.artists_text %}<tr><td class="k">Artist(s) Featured</td><td>{{ e.artists_text }}</td></tr>{% endif %}{% endfor %}
{% if reference %}<tr><td class="k">Reference No.</td><td>{{ reference }}</td></tr>{% endif %}
{% if feedback_url %}<tr><td colspan="2"><a href="{{ feedback_url }}" style="font-weight:bold;text-decoration:none">&#128221; Share your feedback on this programme</a></td></tr>{% endif %}
</table>
<div class="amount"><span>Contribution towards the programme</span><b>&#8377;{{ amount_inr }}</b>{% if amount_words %}<small>{{ amount_words }}</small>{% endif %}</div>
<p>For your records, we have enclosed the details of the contribution towards the programme, along with our bank particulars, should your office wish to process it at its convenience. Contributions from host institutions are what allow us to take artists to more schools and colleges across the country.</p>
{% if bank and bank.account_number %}<div class="bank"><h3>&#127974; Bank particulars (NEFT / RTGS)</h3><table class="facts plain">
<tr><td class="k">Account name</td><td>{{ bank.account_name }}</td></tr>
<tr><td class="k">Account number</td><td>{{ bank.account_number }}</td></tr>
<tr><td class="k">IFSC</td><td>{{ bank.ifsc }}</td></tr>
<tr><td class="k">Bank</td><td>{{ bank.bank_name }}{% if bank.branch %}, {{ bank.branch }}{% endif %}</td></tr>
</table></div>{% endif %}
<p>If this has already been arranged, please do treat this note simply as an acknowledgement, with our thanks.</p>
<p class="attach">&#128206; <b>Attached:</b> Request for Payment (PDF){% if has_poster %} &middot; programme poster{% endif %}</p>
<p>For anything at all, we are reachable at {{ org.info_email }}.</p>
<p>Thank you once again for your support in taking this movement forward.</p>
""" + SIGN + "{% endblock %}"

PAYMENT_REQUEST_TEXT = """{% if institution.contact_name %}Dear {{ institution.contact_name }},{% else %}Dear Sir/Madam,{% endif %}

Greetings from {{ org.name }}!

Thank you for partnering with us to host this programme under the {{ org.name }} movement. We hope the students and faculty enjoyed the session and that it opened a door to India's rich cultural heritage for them.
{% if feedback_url %}
We would love to hear how it went: {{ feedback_url }}
{% endif %}
Institute: {{ institution.name }}
{% for e in events %}Event: {{ e.date }} / {{ e.module }}{% if e.artists_text %} by {{ e.artists_text }}{% endif %}
{% endfor %}{% if reference %}Reference: {{ reference }}
{% endif %}
Contribution towards the programme: Rs {{ amount_inr }} ({{ amount_words }}). The details and our bank particulars are attached.
{% if bank and bank.account_number %}
Bank particulars (NEFT / RTGS): {{ bank.account_name }}, A/c {{ bank.account_number }}, IFSC {{ bank.ifsc }}, {{ bank.bank_name }}{% if bank.branch %} ({{ bank.branch }}){% endif %}
{% endif %}
If this has already been arranged, please treat this note simply as an acknowledgement, with our thanks.

For anything at all, we are reachable at {{ org.info_email }}.

Warm regards,
{{ coordinator.name or org.name + ' Team' }}
{{ org.name }}
{{ org.website_short }}"""

GUIDELINES = """{% extends "email.shell" %}{% block content %}
<p>{% if institution.contact_name %}Dear {{ institution.contact_name }},{% else %}Dear Sir/Madam,{% endif %}</p>
<span class="pill">&#128197; Upcoming {% if events|length > 1 %}Programmes{% else %}Programme{% endif %}</span>
<p>Greetings from {{ org.name }}! We are delighted to confirm the following {% if events|length > 1 %}programmes{% else %}programme{% endif %} at {{ institution.name }}.</p>
<table class="grid"><tr><th>Date</th><th>Time</th><th>Programme</th><th>Artists</th></tr>
{% for e in events %}<tr><td class="nw">{{ e.date }}</td><td>{{ e.time or 'To be confirmed' }}</td><td>{{ e.module }}</td><td>{{ e.artists_text }}</td></tr>{% endfor %}
</table>
<p>To help the session run beautifully, here is a short summary of what we request from the host institution.</p>
<div class="sop">
<h3>Travel</h3><ul><li>Please arrange a well-maintained vehicle to bring the artistes from their place of stay to the venue, and to drop them back.</li><li>Senior students and/or faculty should escort the artistes.</li><li>Kindly ensure the artistes reach the venue one hour before the scheduled start.</li></ul>
<h3>Green room</h3><ul><li>A clean, private green room near the auditorium, preferably with an attached toilet and curtained windows.</li><li>Floor seating (darees or carpets covered with white sheets), plus a table and three or four chairs to the side.</li><li>Drinking water and glasses. The room should be lockable so instruments can be left safely.</li></ul>
<h3>Stage and sound</h3><ul><li>An appropriate stage, with no cloth or carpet covering it. It may be decorated with flowers, rangoli and diyas.</li><li>Only the {{ org.name }} third-eye logo on the backdrop, with no other banners or posters on stage or in the auditorium.</li><li>Sound system provided by the institution. Typical requirement: tabla 1 mike, vocal and harmonium 2 mikes, sitar 1 mike, announcements 2 stand mikes, dance 2 high-quality foot mikes. Full, normal stage lighting and four bottles of mineral water.</li><li>Baithak-style seating in a closed auditorium is ideal, with students seated close to the artistes.</li></ul>
<h3>During the programme</h3><ul><li>Starting on time is crucial. The programme may open with lamp lighting by the head of the institution along with the artiste.</li><li>The compere should have the artiste's bio-data, reconfirmed with them beforehand, and should check the correct sequence for introducing and felicitating the artistes.</li><li>Mobile phones switched off, minimal movement, and no flash photography. Any photography or video needs the artistes' prior consent.</li><li>A 15-minute interactive question-and-answer session closes the programme, followed by felicitation of all artistes and a vote of thanks.</li></ul>
<h3>Hospitality and acknowledgement</h3><ul><li>Light refreshments before and/or after the concert, and breakfast or lunch for the artistes as appropriate. Students serving the artistes themselves adds a lovely touch.</li><li>Bottled water and glasses on or near the stage during the programme.</li><li>Afterwards, a Letter of Acknowledgement on institution letterhead, signed by the head of the institution, to be handed to the {{ org.name }} volunteer.</li></ul>
</div>
{% if has_attachment %}<p class="attach">&#128206; The complete guidelines are attached as a PDF.</p>{% endif %}
<p>Please do reach out if anything above needs discussion; we are glad to help.</p>
""" + SIGN + "{% endblock %}"

ARTIST_ACK = """{% extends "email.shell" %}{% block content %}
<p>Dear {{ artist.name }},</p>
<span class="pill">&#128591; With Gratitude</span>
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
<p>Namaste{% if coordinator.name %} {{ coordinator.name }} ji{% endif %},</p>
<span class="pill">&#9989; {{ aprs|length }} APR{{ 's' if aprs|length != 1 else '' }} Filed</span>
<p>{{ aprs|length }} Artist Payment Request{{ 's' if aprs|length != 1 else '' }} {{ 'were' if aprs|length != 1 else 'was' }} filed together through the APR Assistant. The APR documents are attached.</p>
<table class="grid"><tr><th>APR</th><th>Program</th><th>Dates</th><th>Institutions</th></tr>
{% for a in aprs %}<tr><td><b>{{ a.number }}</b></td><td>{{ a.program }}</td><td>{{ a.dates }}</td><td>{{ a.institutions }}</td></tr>{% endfor %}
</table>
{% if pending %}<p class="note">Still to file: {{ pending }}.</p>{% endif %}
<p>Thank you for promoting Indian classical arts and culture!</p>
<p class="sign"><strong>{{ org.name }} Team</strong><br><em>Spreading the essence of Indian heritage</em></p>
{% endblock %}"""

# Sent when the poster is made after the APR email has already gone, so it can still travel with the APR.
APR_POSTER = """{% extends "email.shell" %}{% block content %}
<p>Namaste{% if coordinator.name %} {{ coordinator.name }} ji{% endif %},</p>
<span class="pill">&#127912; Program Poster</span>
<p>The poster for APR {{ apr.number }} is ready. It is attached here together with the APR document, so both stay together in your records.</p>
<table class="facts">
<tr><td class="k">APR No.</td><td><b>{{ apr.number }}</b></td></tr>
<tr><td class="k">Program</td><td>{{ program.type_label }}{% if program.title %}: {{ program.title }}{% endif %}</td></tr>
<tr><td class="k">Artists</td><td>{% for a in artists %}{{ a.name }}{% if a.art_form %} ({{ a.art_form }}){% endif %}{% if not loop.last %}<br>{% endif %}{% endfor %}</td></tr>
<tr><td class="k">{{ 'Events' if events|length > 1 else 'Event' }}</td><td>{% for e in events %}{{ e.date }}{% if e.time %}, {{ e.time }}{% endif %}: {{ e.institution_line }}{% if not loop.last %}<br>{% endif %}{% endfor %}</td></tr>
</table>
<p class="attach">&#128206; <b>Attached:</b> program poster &middot; APR {{ apr.number }} (PDF)</p>
<p>Thank you for promoting Indian classical arts and culture!</p>
<p class="sign"><strong>{{ org.name }} Team</strong><br><em>Spreading the essence of Indian heritage</em></p>
{% endblock %}"""

HOUSE_RULES = """- Many coordinators are volunteers: be warm, respectful and patient, like a helpful colleague.
- Say "program" for the whole booking and "event" for each session within it.
- Keep each reply short enough to read comfortably on a phone screen.
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
    'email.apr_confirmation': _email('APR filed (to coordinators and finance)',
                                     '{{ org.name }} APR {{ apr.number }} Confirmation – {% if program.title %}{{ program.title }}{% elif events %}'
                                     '{{ events[0].artists_text }}{% if events[0].artists_text %} at {% endif %}{{ events[0].institution_line }}{% endif %}',
                                     APR_CONFIRMATION, ['coordinator.name', 'apr.number', 'program.type_label', 'program.title', 'program.notes', 'artists',
                                                        'events', 'coordinators', 'has_poster', 'has_calendar']),
    'email.apr_poster': _email('Poster for a filed APR (to coordinators and finance)',
                               '{{ org.name }} APR {{ apr.number }}: program poster{% if events %} – {{ events[0].institution_line }}{% endif %}',
                               APR_POSTER, ['coordinator.name', 'apr.number', 'program.type_label', 'artists', 'events']),
    'email.payment_request': _email('Request for Payment (to the institution)',
                                    'Thank You — Programme Feedback & Contribution Details – {{ org.name }} ({{ institution.name }})',
                                    PAYMENT_REQUEST, ['institution.name', 'institution.contact_name', 'events', 'amount_inr', 'amount_words', 'reference',
                                                      'feedback_url', 'coordinator.name', 'bank', 'has_poster'],
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
        'feedback_url': '', 'has_attachment': True, 'has_poster': True, 'has_calendar': True, 'calendar_events': 2, 'year': 2026,
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


# Earlier default wordings: when the stored template is still exactly one of these (nobody edited it), the
# current default replaces it as a new version on startup. An administrator's own wording is never touched.
SUPERSEDED_DEFAULTS = {'prompt.house_rules': [""" + repr(old_rules) + """]}
# v2.0-v2.3 emails: the red-banner look gives way to the earlier app's gold design (and a cleaner APR subject).
from app.core.template_history import V23 as _V23           # noqa: E402
for _k, _body in _V23.items():
    SUPERSEDED_DEFAULTS.setdefault(_k, []).append(_body)


DEFAULT_TEMPLATES['doc.event_guidelines'] = {
    'kind': 'document', 'title': 'Pre-event guidelines document (PDF)', 'body': '',
    'meta': {'file': '', 'help': 'The SOP and pre-programme checklist attached to the pre-event guidelines email. Upload a '
                                 'revised PDF to replace it; earlier versions and the original stay available.'}}
