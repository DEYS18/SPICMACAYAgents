# Added by Claude for SPIC MACAY Agents - Knowledge (RAG) capability.
"""
Drive + RAG Service
===================

Connects to a Google Drive folder (via the Google Drive API), extracts text from
ALL documents inside it (recursively through subfolders), splits the text into
chunks, creates embeddings with OpenAI, and retrieves the most relevant chunks
for a user's question.

Supported file types
--------------------
Google native:   Google Docs, Sheets, Slides
Office uploads:  Word (.docx/.doc), Excel (.xlsx/.xls), PowerPoint (.pptx/.ppt)
Others:          PDF, plain text, CSV, Markdown, HTML, RTF

IMPORTANT / HONEST NOTES
------------------------
- IMPORT-SAFE: missing libraries never crash the app; the agent simply reports
  no documents are indexed yet.
- Indexes are stored locally as .npz + .json files. They are NOT rebuilt on
  every query — call /api/knowledge/<key>/reindex to refresh.
- Folder traversal is fully recursive: all subfolders are walked automatically.
"""

import os
import io
import json
import time
import logging
import html as html_mod
import re
import zipfile
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Optional deps: each imported defensively ──────────────────────────────── #

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception as e:
    _HAS_NUMPY = False
    logger.warning(f"[drive_rag] numpy not available: {e}")

try:
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials as OAuthCredentials
    from google.auth.transport.requests import Request as GoogleRequest
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build as gbuild
    from googleapiclient.http import MediaIoBaseDownload
    _HAS_GOOGLE = True
except Exception as e:
    _HAS_GOOGLE = False
    logger.warning(f"[drive_rag] Google Drive libraries not available: {e}")

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

try:
    from pypdf import PdfReader
    _HAS_PYPDF = True
except Exception:
    _HAS_PYPDF = False

try:
    import docx as _docx_lib          # python-docx
    _HAS_DOCX = True
except Exception:
    _HAS_DOCX = False

try:
    import openpyxl as _openpyxl_lib  # openpyxl
    _HAS_OPENPYXL = True
except Exception:
    _HAS_OPENPYXL = False

try:
    from pptx import Presentation as _PptxPresentation   # python-pptx
    _HAS_PPTX = True
except Exception:
    _HAS_PPTX = False

# ── MIME type constants ────────────────────────────────────────────────────── #

_GOOGLE_FOLDER   = "application/vnd.google-apps.folder"
_GOOGLE_SHORTCUT = "application/vnd.google-apps.shortcut"
_GOOGLE_DOC      = "application/vnd.google-apps.document"
_GOOGLE_SHEET    = "application/vnd.google-apps.spreadsheet"
_GOOGLE_SLIDE    = "application/vnd.google-apps.presentation"
_GOOGLE_FORM     = "application/vnd.google-apps.form"

_PDF      = "application/pdf"
_PLAIN    = "text/plain"
_CSV      = "text/csv"
_HTML     = "text/html"
_MARKDOWN = "text/markdown"
_RTF      = "application/rtf"

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_DOC  = "application/msword"
_XLS  = "application/vnd.ms-excel"
_PPT  = "application/vnd.ms-powerpoint"

# All types this service can extract text from.
_SUPPORTED_MIMES = {
    _GOOGLE_DOC, _GOOGLE_SHEET, _GOOGLE_SLIDE, _GOOGLE_FORM,
    _PDF, _PLAIN, _CSV, _HTML, _MARKDOWN, _RTF,
    _DOCX, _XLSX, _PPTX, _DOC, _XLS, _PPT,
}


class DriveRagService:
    """Builds and queries a local vector index over all Google Drive documents."""

    def __init__(
        self,
        openai_client,
        embedding_model: str = "text-embedding-3-small",
        index_dir: str = "knowledge_index",
        chunk_size: int = 1200,
        chunk_overlap: int = 200,
    ):
        self.client = openai_client
        self.embedding_model = embedding_model
        self.index_dir = index_dir
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        os.makedirs(self.index_dir, exist_ok=True)

    # ── Google Drive auth ──────────────────────────────────────────────────── #

    def _drive_available(self) -> bool:
        if not _HAS_GOOGLE:
            return False
        token_file = os.getenv("GOOGLE_TOKEN_FILE", "credentials/token.json")
        if os.path.exists(token_file):
            return True
        svc_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
        return bool(svc_file) and os.path.exists(svc_file)

    def _get_drive(self):
        """Return an authenticated Drive v3 client. Prefers OAuth2 token."""
        token_file = os.getenv("GOOGLE_TOKEN_FILE", "credentials/token.json")
        if os.path.exists(token_file):
            creds = OAuthCredentials.from_authorized_user_file(token_file, _DRIVE_SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(GoogleRequest())
                with open(token_file, "w") as fh:
                    fh.write(creds.to_json())
            return gbuild("drive", "v3", credentials=creds, cache_discovery=False)

        svc_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if svc_file and os.path.exists(svc_file):
            creds = service_account.Credentials.from_service_account_file(
                svc_file, scopes=_DRIVE_SCOPES
            )
            return gbuild("drive", "v3", credentials=creds, cache_discovery=False)

        raise RuntimeError(
            "No Google credentials found. Run setup_google_auth.py first, "
            "or set GOOGLE_SERVICE_ACCOUNT_FILE in .env"
        )

    # ── Recursive folder listing ───────────────────────────────────────────── #

    def _list_files_recursive(self, drive, folder_id: str,
                               path_prefix: str = "") -> List[Dict]:
        """
        Walk a Drive folder tree and return every supported file with its
        full path stored in the 'path' key (e.g. 'Subfolder/Doc.pdf').
        """
        results = []
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"

        while True:
            resp = (
                drive.files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime, shortcutDetails)",
                    pageToken=page_token,
                    pageSize=100,
                )
                .execute()
            )
            for item in resp.get("files", []):
                item_path = f"{path_prefix}{item['name']}" if path_prefix else item["name"]
                mime = item["mimeType"]

                if mime == _GOOGLE_FOLDER:
                    # Real subfolder → recurse
                    sub = self._list_files_recursive(
                        drive, item["id"], path_prefix=item_path + "/"
                    )
                    results.extend(sub)

                elif mime == _GOOGLE_SHORTCUT:
                    # Drive shortcut — resolve to the target file or folder
                    sc = item.get("shortcutDetails") or {}
                    target_id   = sc.get("targetId",       "")
                    target_mime = sc.get("targetMimeType", "")
                    if not target_id:
                        logger.debug(f"[drive_rag] Shortcut '{item['name']}' has no targetId — skipping")
                        continue
                    if target_mime == _GOOGLE_FOLDER:
                        # Shortcut to a folder -> recurse into the target folder
                        logger.info(f"[drive_rag] Following shortcut '{item['name']}' -> folder {target_id}")
                        sub = self._list_files_recursive(
                            drive, target_id, path_prefix=item_path + "/"
                        )
                        results.extend(sub)
                    elif target_mime in _SUPPORTED_MIMES:
                        # Shortcut to a supported file -> index the target file
                        logger.info(f"[drive_rag] Following shortcut '{item['name']}' -> file {target_id}")
                        results.append({
                            "id":       target_id,
                            "name":     item["name"],
                            "mimeType": target_mime,
                            "path":     item_path,
                        })
                    else:
                        logger.debug(
                            f"[drive_rag] Shortcut '{item['name']}' points to unsupported type '{target_mime}'"
                        )

                elif mime in _SUPPORTED_MIMES:
                    item["path"] = item_path
                    results.append(item)

                else:
                    logger.debug(
                        f"[drive_rag] Skipping unsupported type '{mime}': {item['name']}"
                    )

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return results

    def list_drive_documents(self, folder_id: str) -> List[Dict]:
        """Public method: list all supported files recursively under folder_id."""
        drive = self._get_drive()
        return self._list_files_recursive(drive, folder_id)

    # ── Text extraction ────────────────────────────────────────────────────── #

    def _download_raw(self, drive, file_id: str) -> bytes:
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, drive.files().get_media(fileId=file_id))
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    def _export_google_native(self, drive, file_id: str, export_mime: str) -> str:
        data = drive.files().export(fileId=file_id, mimeType=export_mime).execute()
        return data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)

    def _download_drive_text(self, drive, file_meta: Dict) -> str:
        """Extract plain text from any supported Drive file."""
        fid  = file_meta["id"]
        mime = file_meta["mimeType"]
        name = file_meta.get("name", fid)

        try:
            # ── Google-native formats ──────────────────────────────────── #
            if mime == _GOOGLE_DOC:
                return self._export_google_native(drive, fid, "text/plain")

            if mime == _GOOGLE_SHEET:
                return self._export_google_native(drive, fid, "text/csv")

            if mime == _GOOGLE_SLIDE:
                return self._export_google_native(drive, fid, "text/plain")

            if mime == _GOOGLE_FORM:
                # Forms export as a ZIP containing an HTML representation
                raw = drive.files().export(fileId=fid, mimeType="application/zip").execute()
                return self._form_to_text(raw if isinstance(raw, bytes) else raw.encode())

            # ── Downloaded binary / text formats ──────────────────────── #
            raw = self._download_raw(drive, fid)

            if mime == _PDF:
                return self._pdf_to_text(io.BytesIO(raw))

            if mime in (_PLAIN, _CSV, _MARKDOWN, _RTF):
                return raw.decode("utf-8", errors="ignore")

            if mime == _HTML:
                return self._html_to_text(raw.decode("utf-8", errors="ignore"))

            if mime == _DOCX or (mime == _DOC and raw[:4] == b'PK\x03\x04'):
                return self._docx_to_text(io.BytesIO(raw))

            if mime == _XLSX or (mime == _XLS and raw[:4] == b'PK\x03\x04'):
                return self._xlsx_to_text(io.BytesIO(raw))

            if mime == _PPTX or (mime == _PPT and raw[:4] == b'PK\x03\x04'):
                return self._pptx_to_text(io.BytesIO(raw))

            # Legacy .doc / .xls (true binary OLE format) — try as UTF-8 text
            # (rough but better than nothing; user should convert to modern formats)
            if mime in (_DOC, _XLS, _PPT):
                logger.warning(
                    f"[drive_rag] '{name}' is a legacy binary Office file. "
                    "Text extraction is limited. Convert to .docx/.xlsx/.pptx for best results."
                )
                return raw.decode("latin-1", errors="ignore")

        except Exception as e:
            logger.error(f"[drive_rag] Could not read '{name}': {e}")

        return ""

    # ── File-type parsers ──────────────────────────────────────────────────── #

    @staticmethod
    def _pdf_to_text(buf: io.BytesIO) -> str:
        if not _HAS_PYPDF:
            logger.warning("[drive_rag] pypdf not installed; skipping PDF.")
            return ""
        try:
            reader = PdfReader(buf)
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as e:
            logger.error(f"[drive_rag] PDF parse error: {e}")
            return ""

    @staticmethod
    def _docx_to_text(buf: io.BytesIO) -> str:
        if not _HAS_DOCX:
            logger.warning("[drive_rag] python-docx not installed; skipping Word doc.")
            return ""
        try:
            doc = _docx_lib.Document(buf)
            parts = []
            for para in doc.paragraphs:
                if para.text.strip():
                    parts.append(para.text)
            for table in doc.tables:
                for row in table.rows:
                    parts.append("\t".join(cell.text for cell in row.cells))
            return "\n".join(parts)
        except Exception as e:
            logger.error(f"[drive_rag] Word parse error: {e}")
            return ""

    @staticmethod
    def _xlsx_to_text(buf: io.BytesIO) -> str:
        if not _HAS_OPENPYXL:
            logger.warning("[drive_rag] openpyxl not installed; skipping Excel file.")
            return ""
        try:
            wb = _openpyxl_lib.load_workbook(buf, read_only=True, data_only=True)
            parts = []
            for sheet in wb.worksheets:
                parts.append(f"[Sheet: {sheet.title}]")
                for row in sheet.iter_rows(values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    line = "\t".join(cells).strip()
                    if line:
                        parts.append(line)
            return "\n".join(parts)
        except Exception as e:
            logger.error(f"[drive_rag] Excel parse error: {e}")
            return ""

    @staticmethod
    def _pptx_to_text(buf: io.BytesIO) -> str:
        if not _HAS_PPTX:
            logger.warning("[drive_rag] python-pptx not installed; skipping PowerPoint.")
            return ""
        try:
            prs = _PptxPresentation(buf)
            parts = []
            for i, slide in enumerate(prs.slides, 1):
                parts.append(f"[Slide {i}]")
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        parts.append(shape.text)
            return "\n".join(parts)
        except Exception as e:
            logger.error(f"[drive_rag] PowerPoint parse error: {e}")
            return ""

    @staticmethod
    def _form_to_text(raw: bytes) -> str:
        """Extract question text from a Google Form exported as a ZIP of HTML files."""
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                parts = []
                for name in zf.namelist():
                    if name.lower().endswith((".html", ".htm")):
                        html = zf.read(name).decode("utf-8", errors="ignore")
                        parts.append(DriveRagService._html_to_text(html))
                return "\n".join(parts)
        except Exception as e:
            logger.error(f"[drive_rag] Google Form ZIP parse error: {e}")
            return ""

    @staticmethod
    def _drive_url(file_id: str, mime: str) -> str:
        """Construct the correct Google Drive/Docs URL for a file."""
        if not file_id:
            return ""
        if mime == _GOOGLE_DOC:
            return f"https://docs.google.com/document/d/{file_id}/edit"
        if mime == _GOOGLE_SHEET:
            return f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
        if mime == _GOOGLE_SLIDE:
            return f"https://docs.google.com/presentation/d/{file_id}/edit"
        if mime == _GOOGLE_FORM:
            return f"https://docs.google.com/forms/d/{file_id}/edit"
        return f"https://drive.google.com/file/d/{file_id}/view"

    @staticmethod
    def _html_to_text(html: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html)
        text = html_mod.unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    # ── Chunking + embeddings ──────────────────────────────────────────────── #

    def _chunk(self, text: str) -> List[str]:
        text = " ".join(text.split())
        if not text:
            return []
        chunks, start = [], 0
        while start < len(text):
            end = start + self.chunk_size
            chunks.append(text[start:end])
            start = end - self.chunk_overlap
            if start < 0:
                start = 0
        return chunks

    def _embed(self, texts: List[str]) -> "np.ndarray":
        vectors = []
        batch = 64
        for i in range(0, len(texts), batch):
            part = texts[i: i + batch]
            resp = self.client.embeddings.create(model=self.embedding_model, input=part)
            vectors.extend([d.embedding for d in resp.data])
            time.sleep(0.05)
        return np.array(vectors, dtype="float32")

    # ── Index build / load / query ─────────────────────────────────────────── #

    def _index_paths(self, index_name: str) -> Tuple[str, str]:
        base = os.path.join(self.index_dir, index_name)
        return base + ".npz", base + ".chunks.json"

    def build_index(self, index_name: str, folder_id: Optional[str] = None,
                    local_folder: Optional[str] = None) -> Dict:
        """
        Build (or rebuild) an index for one agent.
        Traverses ALL subfolders recursively when reading from Google Drive.
        Falls back to a local folder when Drive is not configured.
        """
        if not _HAS_NUMPY:
            return {"success": False, "error": "numpy is not installed (pip install numpy)."}

        records = []   # list of {text, source}
        skipped = []

        if folder_id and self._drive_available():
            logger.info(f"[drive_rag] Building '{index_name}' from Drive folder {folder_id} (recursive)")
            drive = self._get_drive()
            all_files = self._list_files_recursive(drive, folder_id)
            logger.info(f"[drive_rag] Found {len(all_files)} supported files")

            for f in all_files:
                text = self._download_drive_text(drive, f)
                if not text.strip():
                    skipped.append(f["path"])
                    continue
                for c in self._chunk(text):
                    records.append({
                        "text": c,
                        "source": f["path"],
                        "file_id": f["id"],
                        "mime": f["mimeType"],
                    })

        elif local_folder and os.path.isdir(local_folder):
            logger.info(f"[drive_rag] Drive not configured; indexing local folder {local_folder}")
            for dirpath, _, fnames in os.walk(local_folder):
                for fname in fnames:
                    fpath = os.path.join(dirpath, fname)
                    rel   = os.path.relpath(fpath, local_folder)
                    text  = ""
                    lo = fname.lower()
                    if lo.endswith((".txt", ".md", ".csv", ".rtf")):
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                            text = fh.read()
                    elif lo.endswith(".pdf"):
                        with open(fpath, "rb") as fh:
                            text = self._pdf_to_text(io.BytesIO(fh.read()))
                    elif lo.endswith(".docx"):
                        with open(fpath, "rb") as fh:
                            text = self._docx_to_text(io.BytesIO(fh.read()))
                    elif lo.endswith(".xlsx"):
                        with open(fpath, "rb") as fh:
                            text = self._xlsx_to_text(io.BytesIO(fh.read()))
                    elif lo.endswith(".pptx"):
                        with open(fpath, "rb") as fh:
                            text = self._pptx_to_text(io.BytesIO(fh.read()))
                    elif lo.endswith(".html"):
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                            text = self._html_to_text(fh.read())
                    for c in self._chunk(text):
                        records.append({"text": c, "source": rel})
        else:
            return {
                "success": False,
                "error": "No source available. Run setup_google_auth.py and set folder IDs in .env, "
                         "or provide a local_folder with documents.",
            }

        if not records:
            return {"success": False, "error": "No readable content found in any document."}

        vectors = self._embed([r["text"] for r in records])
        npz_path, chunks_path = self._index_paths(index_name)
        np.savez_compressed(npz_path, vectors=vectors)
        with open(chunks_path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False)

        unique_docs = sorted(set(r["source"] for r in records))
        logger.info(
            f"[drive_rag] Index '{index_name}' built: {len(records)} chunks "
            f"from {len(unique_docs)} documents."
        )
        result = {
            "success": True,
            "chunks": len(records),
            "documents": unique_docs,
        }
        if skipped:
            result["skipped"] = skipped
        return result

    def has_index(self, index_name: str) -> bool:
        npz_path, chunks_path = self._index_paths(index_name)
        return os.path.exists(npz_path) and os.path.exists(chunks_path)

    def retrieve(self, index_name: str, query: str, k: int = 5) -> List[Dict]:
        """Return the top-k most relevant chunks for a query."""
        if not _HAS_NUMPY or not self.has_index(index_name):
            return []
        npz_path, chunks_path = self._index_paths(index_name)
        vectors = np.load(npz_path)["vectors"]
        with open(chunks_path, "r", encoding="utf-8") as fh:
            records = json.load(fh)

        q = self._embed([query])[0]
        denom = (np.linalg.norm(vectors, axis=1) * np.linalg.norm(q)) + 1e-8
        sims  = (vectors @ q) / denom
        top   = np.argsort(sims)[::-1][:k]
        return [
            {
                "text": records[i]["text"],
                "source": records[i]["source"],
                "score": float(sims[i]),
                "url": self._drive_url(
                    records[i].get("file_id", ""),
                    records[i].get("mime", ""),
                ),
            }
            for i in top
        ]
