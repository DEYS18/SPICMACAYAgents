"""
Outgoing email for the assistant: plain + HTML alternatives, attachments, CC, dry-run.

In dry-run (Admin setting, or whenever SMTP isn't configured) messages are rendered in full
and saved as .eml files under instance/outbox instead of being sent, so templates can be
checked safely on a staging server. Every send or dry run is written to the audit log.
"""
import logging
import os
import re
import smtplib
import time
import uuid
from email.message import EmailMessage
from email.utils import make_msgid

logger = logging.getLogger(__name__)


class Mailer:
    def __init__(self, smtp: dict, governance, outbox_dir: str):
        self.smtp = smtp or {}
        self.gov = governance
        self.outbox_dir = outbox_dir

    @property
    def configured(self) -> bool:
        return bool(self.smtp.get('user') and self.smtp.get('password') and self.smtp.get('host'))

    def send(self, *, to, subject, html, text=None, cc=None, attachments=None, actor='system', category='email') -> dict:
        to = [a for a in dict.fromkeys(x.strip() for x in (to or []) if x and '@' in x)]
        cc = [a for a in dict.fromkeys(x.strip() for x in (cc or []) if x and '@' in x) if a.lower() not in {t.lower() for t in to}]
        if not to:
            return {'ok': False, 'error': 'No valid recipient address'}
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = self.smtp.get('from_email') or self.smtp.get('user') or 'noreply@spicmacay.org'
        msg['To'] = ', '.join(to)
        if cc:
            msg['Cc'] = ', '.join(cc)
        msg['Message-ID'] = make_msgid(domain='spicmacay.org')
        msg.set_content(text or re.sub(r'<[^>]+>', '', html or ''))
        msg.add_alternative(html or '', subtype='html')
        for name, data, mime in attachments or []:
            if not data:
                continue
            maintype, _, subtype = (mime or 'application/octet-stream').partition('/')
            msg.add_attachment(data, maintype=maintype, subtype=subtype or 'octet-stream', filename=name)
        dry = bool(self.gov.get_setting('email.dry_run', False)) or not self.configured
        details = {'to': to, 'cc': cc, 'subject': subject, 'category': category,
                   'attachments': [a[0] for a in attachments or [] if a[1]]}
        if dry:
            os.makedirs(self.outbox_dir, exist_ok=True)
            path = os.path.join(self.outbox_dir, f"{time.strftime('%Y%m%d-%H%M%S')}-{category}-{uuid.uuid4().hex[:8]}.eml")
            with open(path, 'wb') as fh:
                fh.write(bytes(msg))
            self.gov.audit(actor, 'email.dry_run', category, dict(details, file=os.path.basename(path)))
            return {'ok': True, 'dry_run': True, 'reason': 'dry-run setting' if self.configured else 'SMTP not configured'}
        try:
            host, port = self.smtp.get('host'), int(self.smtp.get('port') or 587)
            server = smtplib.SMTP_SSL(host, port, timeout=25) if port == 465 else smtplib.SMTP(host, port, timeout=25)
            with server:
                if port != 465:
                    server.starttls()
                server.login(self.smtp['user'], self.smtp['password'])
                server.send_message(msg, to_addrs=to + cc)
            self.gov.audit(actor, 'email.sent', category, details)
            return {'ok': True, 'dry_run': False}
        except Exception as e:
            logger.error('Email send failed (%s): %s', category, e)
            self.gov.audit(actor, 'email.failed', category, dict(details, error=str(e)))
            return {'ok': False, 'error': str(e)}
