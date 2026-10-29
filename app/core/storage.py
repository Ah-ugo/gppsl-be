"""File storage. Cloudinary free tier when CLOUDINARY_URL is set, otherwise the local uploads folder."""
import asyncio
import os
import re
import tempfile
from pathlib import Path

from .common import new_id
from .config import get_settings


def upload_folder() -> Path:
    """Return a writable folder for uploads.

    On read-only filesystems (e.g. Vercel serverless) fall back to the
    system temp directory so the app can still start and serve files.
    """
    s = get_settings()
    primary = Path(s.upload_dir)
    try:
        primary.mkdir(parents=True, exist_ok=True)
        probe = primary / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return primary
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "gppsl_uploads"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name or "file")[-80:]


async def save_bytes(data: bytes, filename: str, content_type: str = "application/octet-stream") -> dict:
    """Returns {"url", "storage": "cloudinary"|"local"}. Always retains a local copy in uploads/."""
    import io
    s = get_settings()
    folder = upload_folder()
    stored = f"{new_id()}_{_safe_name(filename)}"
    (folder / stored).write_bytes(data)

    if s.cloudinary_url:
        try:
            import cloudinary
            import cloudinary.uploader
            from urllib.parse import urlparse

            p = urlparse(s.cloudinary_url)
            cloudinary.config(
                cloud_name=p.hostname,
                api_key=p.username,
                api_secret=p.password,
                secure=True,
            )
            # Use raw for documents to avoid Cloudinary anti-malware delivery restrictions on PDF/ZIP
            r_type = "raw" if filename.lower().endswith((".pdf", ".doc", ".docx", ".zip")) else "auto"
            res = await asyncio.to_thread(
                cloudinary.uploader.upload,
                io.BytesIO(data),
                resource_type=r_type,
                folder="gppsl",
                public_id=f"{new_id()}_{_safe_name(filename)}",
            )
            return {"url": res["secure_url"], "storage": "cloudinary", "local_path": str(folder / stored)}
        except Exception:  # noqa: BLE001 - fall back to local so the system keeps working
            pass

    return {"url": f"{s.public_base_url.rstrip('/')}/uploads/{stored}", "storage": "local"}


def read_local(url: str) -> bytes | None:
    """Read back a locally stored file from its URL or search uploads for matching filename."""
    marker = "/uploads/"
    folder = upload_folder()
    if marker in url:
        fname = url.split(marker, 1)[1]
        p = folder / fname
        if p.exists():
            return p.read_bytes()

    # Search folder for filename matching the tail of the URL
    tail = url.split("/")[-1].split("?")[0]
    # Clean possible duplicate extensions like .pdf.pdf
    if tail.endswith(".pdf.pdf"):
        tail = tail[:-4]
    p = folder / tail
    if p.exists():
        return p.read_bytes()

    # Try matching without uuid prefix
    clean_tail = re.sub(r"^[a-f0-9-]+_", "", tail)
    for f in folder.glob("*"):
        if clean_tail and clean_tail in f.name:
            return f.read_bytes()

    return None

