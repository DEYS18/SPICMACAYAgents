"""Generated documents live outside /static and are served only through an authenticated
route, because APRs and invoices carry phone numbers, emails and bank details."""
import os
import re

PUBLIC_KINDS = {'apr', 'rfp', 'poster', 'docs', 'preview'}
PRIVATE_KINDS = {'cheques', 'uploads'}


class OutputStore:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        for k in PUBLIC_KINDS | PRIVATE_KINDS:
            os.makedirs(os.path.join(self.root, k), exist_ok=True)

    @staticmethod
    def safe_name(name: str) -> str:
        name = re.sub(r'[^A-Za-z0-9._-]+', '_', os.path.basename(name or 'file'))
        return name.strip('._') or 'file'

    def path(self, kind: str, filename: str) -> str:
        if kind not in PUBLIC_KINDS | PRIVATE_KINDS:
            raise ValueError('Unknown file kind')
        p = os.path.abspath(os.path.join(self.root, kind, self.safe_name(filename)))
        if not p.startswith(os.path.join(self.root, kind) + os.sep):
            raise ValueError('Bad path')
        return p

    def save(self, kind: str, filename: str, data: bytes) -> str:
        name = self.safe_name(filename)
        with open(self.path(kind, name), 'wb') as fh:
            fh.write(data)
        return name

    def read(self, kind: str, filename: str) -> bytes:
        with open(self.path(kind, filename), 'rb') as fh:
            return fh.read()

    def exists(self, kind: str, filename: str) -> bool:
        try:
            return os.path.exists(self.path(kind, filename))
        except ValueError:
            return False
