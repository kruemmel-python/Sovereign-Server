from __future__ import annotations

import dataclasses, re, tempfile
from pathlib import Path
from typing import BinaryIO, Mapping

from .errors import HTTPError
from .request import Request


@dataclasses.dataclass
class UploadedFile:
    name: str
    filename: str
    content_type: str
    size: int
    file: tempfile.SpooledTemporaryFile
    sniffed_type: str | None = None

    def read(self) -> bytes:
        self.file.seek(0)
        return self.file.read()

    def save(self, path: str | Path) -> None:
        self.file.seek(0)
        with open(path, "wb") as out:
            while True:
                chunk = self.file.read(65536)
                if not chunk:
                    break
                out.write(chunk)


@dataclasses.dataclass
class MultipartData:
    fields: dict[str, str]
    files: dict[str, UploadedFile]


_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"%PDF-": "application/pdf",
    b"PK\x03\x04": "application/zip",
    b"MZ": "application/vnd.microsoft.portable-executable",
    b"#!": "text/x-shellscript",
}


def sniff_mime(head: bytes) -> str | None:
    for magic, mime in _MAGIC.items():
        if head.startswith(magic):
            return mime
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        return "application/xml"
    return None


def _parse_content_disposition(value: str) -> tuple[str, dict[str, str]]:
    pieces = [p.strip() for p in value.split(";")]
    kind = pieces[0].lower()
    params: dict[str, str] = {}
    for p in pieces[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.strip().lower()] = v.strip().strip('"')
    return kind, params


def _headers(block: bytes) -> Mapping[str, str]:
    headers = {}
    for line in block.decode("iso-8859-1").split("\r\n"):
        if not line:
            continue
        if "\r" in line or "\n" in line or ":" not in line:
            raise HTTPError(400, "Malformed multipart header")
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()
    return headers


class MultipartParser:
    """Bounded multipart/form-data parser with hard part/file limits and magic-byte checks.

    The socket layer already spools large request bodies to disk, so this parser
    keeps individual files in SpooledTemporaryFile and enforces per-file limits.
    """

    def __init__(self, *, max_files: int = 8, max_file_size: int = 10 * 1024 * 1024,
                 max_parts: int = 64, spool_size: int = 512 * 1024,
                 allowed_mime_mismatch: bool = False) -> None:
        self.max_files = max_files
        self.max_file_size = max_file_size
        self.max_parts = max_parts
        self.spool_size = spool_size
        self.allowed_mime_mismatch = allowed_mime_mismatch

    def parse(self, req: Request) -> MultipartData:
        ctype = req.header("content-type")
        m = re.search(r'boundary=("?)([^";]+)\1', ctype)
        if "multipart/form-data" not in ctype or not m:
            raise HTTPError(400, "Expected multipart/form-data")
        boundary = m.group(2).encode("ascii", errors="strict")
        if not boundary or len(boundary) > 200 or b"\r" in boundary or b"\n" in boundary:
            raise HTTPError(400, "Invalid multipart boundary")
        raw = req.body_bytes()
        sep = b"--" + boundary
        if sep not in raw:
            raise HTTPError(400, "Multipart boundary not found")

        fields: dict[str, str] = {}
        files: dict[str, UploadedFile] = {}
        file_count = 0
        part_count = 0

        for part in raw.split(sep)[1:]:
            if part.startswith(b"--"):
                break
            if part.startswith(b"\r\n"):
                part = part[2:]
            if part.endswith(b"\r\n"):
                part = part[:-2]
            if not part:
                continue
            part_count += 1
            if part_count > self.max_parts:
                raise HTTPError(413, "Too many multipart parts")
            if b"\r\n\r\n" not in part:
                raise HTTPError(400, "Malformed multipart part")
            header_block, content = part.split(b"\r\n\r\n", 1)
            headers = _headers(header_block)
            disp, params = _parse_content_disposition(headers.get("content-disposition", ""))
            if disp != "form-data" or "name" not in params:
                raise HTTPError(400, "Invalid content disposition")
            name = params["name"]
            filename = params.get("filename")
            if filename is None:
                fields[name] = content.decode("utf-8", errors="replace")
                continue
            file_count += 1
            if file_count > self.max_files:
                raise HTTPError(413, "Too many uploaded files")
            if len(content) > self.max_file_size:
                raise HTTPError(413, "Uploaded file too large")
            content_type = headers.get("content-type", "application/octet-stream").lower()
            sniffed = sniff_mime(content[:8])
            dangerous = {"application/vnd.microsoft.portable-executable", "text/x-shellscript"}
            if sniffed in dangerous:
                raise HTTPError(415, "Dangerous uploaded file type rejected")
            if sniffed and content_type.startswith(("image/", "application/pdf", "application/zip")) and sniffed != content_type and not self.allowed_mime_mismatch:
                raise HTTPError(415, f"MIME mismatch: declared {content_type}, got {sniffed}")
            spool = tempfile.SpooledTemporaryFile(max_size=self.spool_size, mode="w+b")
            spool.write(content)
            spool.seek(0)
            files[name] = UploadedFile(name=name, filename=filename, content_type=content_type,
                                       size=len(content), file=spool, sniffed_type=sniffed)
        return MultipartData(fields=fields, files=files)


def parse_multipart(req: Request, **limits: int) -> MultipartData:
    return MultipartParser(**limits).parse(req)
