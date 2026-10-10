"""
Governed documents: files sent as attachments, starting with the pre-event guidelines PDF (the SOP and checklist
that goes to institutions). In Admin > Templates > Event guidelines an administrator can upload a revised PDF as a
new version; every version is kept, any can be switched back on, and the original that ships with the app is
always available. Both assistants attach whichever version is active.
"""
import hashlib
import os
import re
import time

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCUMENTS = {
    'doc.event_guidelines': {
        'title': 'Pre-event guidelines document (PDF)',
        'name': 'SPIC_MACAY_Event_Guidelines.pdf',
        'default': os.path.join(APP_DIR, 'static', 'guidelines', 'event_institution_guidelines.pdf'),
        'help': 'The SOP and pre-programme checklist attached to the pre-event guidelines email. Upload a revised PDF to '
                'replace it; earlier versions and the original stay available.'},
}
MAX_BYTES = 15 * 1024 * 1024


def _version_meta(services, key, version=None):
    try:
        return ((services.gov.get_template(key, version) if version else services.gov.get_template(key)) or {}).get('meta') or {}
    except Exception:
        return {}


def document_path(services, key, version=None):
    """(path, attachment name) of the active version (or of one version), else the original that ships with the app."""
    spec = DOCUMENTS[key]
    meta = _version_meta(services, key, version) if services else {}
    if meta.get('file') and os.path.exists(meta['file']):
        return meta['file'], spec['name']
    return spec['default'], spec['name']


def instance_dir(services):
    for attr in ('instance_dir',):
        if getattr(services, attr, None):
            return services.instance_dir
    for attr in ('path', 'db_path', 'filename'):
        p = getattr(services.gov, attr, None)
        if isinstance(p, str) and p:
            return os.path.dirname(os.path.abspath(p))
    return os.path.join(os.path.dirname(APP_DIR), 'instance')


def store_upload(services, key, data, filename):
    """Keep an uploaded PDF in the instance folder (back it up with the rest of instance/)."""
    if not data or data[:5] != b'%PDF-':
        raise ValueError('That file is not a PDF.')
    if len(data) > MAX_BYTES:
        raise ValueError('The file is larger than 15 MB.')
    folder = os.path.join(instance_dir(services), 'documents', key.replace('.', '_'))
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', os.path.basename(filename or 'document.pdf'))[-80:] or 'document.pdf'
    path = os.path.join(folder, time.strftime('%Y%m%d-%H%M%S-') + safe)
    with open(path, 'wb') as fh:
        fh.write(data)
    return {'file': path, 'original_name': os.path.basename(filename or safe), 'size': len(data),
            'sha256': hashlib.sha256(data).hexdigest(), 'help': DOCUMENTS[key]['help']}
