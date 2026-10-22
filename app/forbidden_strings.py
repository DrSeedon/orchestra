"""Publish guard (V-1014): strings that must never reach a public repository.

The list lives OUTSIDE git (`data/secrets/forbidden-strings.txt`, one string per line, `#`
comments). Matches are reported by rule number only — the value itself is never printed.
Stdlib only: `scripts/secret_scan.py` imports this module in the pre-push hook.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app import publication_secrets

ENV_VAR = "ORCHESTRA_FORBIDDEN_STRINGS"
REL_PATH = Path("data/secrets/forbidden-strings.txt")

# Per Git blob, including intermediate layers and metadata. Never extract to disk.
ARCHIVE_MAX_BYTES = 16 * 1024 * 1024
ARCHIVE_MAX_INPUT_BYTES = 16 * 1024 * 1024
ARCHIVE_MAX_MEMBERS = 1000
ARCHIVE_MAX_DEPTH = 4
_CHUNK = 64 * 1024


class _ArchiveError(Exception):
    """Only fixed, non-secret reasons belong in this exception."""


class _ArchiveBudget:
    def __init__(self):
        self.remaining = ARCHIVE_MAX_BYTES
        self.members = 0

    def consume(self, size: int) -> None:
        self.remaining -= size
        if self.remaining < 0:
            raise _ArchiveError("decompressed byte limit exceeded")

    def member(self) -> None:
        self.members += 1
        if self.members > ARCHIVE_MAX_MEMBERS:
            raise _ArchiveError("archive member limit exceeded")

    def read(self, stream) -> bytes:
        result = bytearray()
        while chunk := stream.read(min(_CHUNK, self.remaining + 1)):
            self.consume(len(chunk))
            result.extend(chunk)
        return bytes(result)


def _archive_kind(data: bytes) -> str | None:
    if data.startswith(b"\x1f\x8b"):
        return "gzip"
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    if data.startswith(b"BZh"):
        return "bzip2"
    if data.startswith(b"\xfd7zXZ\x00"):
        return "xz"
    if data[257:263] in (b"ustar\x00", b"ustar "):
        return "tar"
    # Old-format tar has no magic; recognize a valid header checksum or empty tar.
    if len(data) >= 512:
        import tarfile

        if len(data) >= 1024 and data[:1024] == bytes(1024):
            return "tar"
        try:
            tarfile.TarInfo.frombuf(data[:512], "utf-8", "surrogateescape")
            return "tar"
        except tarfile.HeaderError:
            pass
    return None


def _inflate(data: bytes, kind: str, budget: _ArchiveBudget, *, concatenated: bool = True,
             metadata=None) -> bytes:
    import bz2
    import lzma
    import zlib

    if not data:
        raise _ArchiveError("corrupt or truncated compressed stream")
    result = bytearray()
    while data:
        budget.member()  # Concatenated streams share the same budget.
        if kind == "gzip" and metadata is not None:
            if len(data) < 10:
                raise _ArchiveError("corrupt gzip header")
            offset, flags = 10, data[3]
            if flags & 4:  # FEXTRA
                if offset + 2 > len(data):
                    raise _ArchiveError("corrupt gzip header")
                offset += 2 + int.from_bytes(data[offset:offset + 2], "little")
            for flag in (8, 16):  # FNAME, FCOMMENT
                if flags & flag:
                    end = data.find(b"\0", offset)
                    if end < 0:
                        raise _ArchiveError("corrupt gzip header")
                    offset = end + 1
            if offset > len(data):
                raise _ArchiveError("corrupt gzip header")
            budget.consume(offset - 10)
            metadata(data[10:offset])
        if kind in ("gzip", "deflate"):
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS if kind == "gzip" else -zlib.MAX_WBITS)
        elif kind == "bzip2":
            decoder = bz2.BZ2Decompressor()
        else:
            decoder = lzma.LZMADecompressor(memlimit=32 * 1024 * 1024)
        pending = data
        while True:
            chunk = decoder.decompress(pending, min(_CHUNK, budget.remaining + 1))
            budget.consume(len(chunk))
            result.extend(chunk)
            if decoder.eof:
                data = decoder.unused_data
                break
            pending = decoder.unconsumed_tail if kind in ("gzip", "deflate") else b""
            if not pending and (not chunk if kind in ("gzip", "deflate") else decoder.needs_input):
                raise _ArchiveError("corrupt or truncated compressed stream")
        if not concatenated and data:
            raise _ArchiveError("corrupt zip compressed stream")
        if kind in ("gzip", "xz"):
            padding = len(data) - len(data.lstrip(b"\0"))
            if kind == "xz" and padding % 4:
                raise _ArchiveError("corrupt xz padding")
            data = data[padding:]
    return bytes(result)


def _zip_payload(payload: bytes, archive, member, budget: _ArchiveBudget) -> bytes:
    import struct
    import zipfile
    import zlib

    # ZipFile validates local names, unsupported flags and overlapping spans, but
    # ZipExtFile's BZIP2 path decompresses without max_length. Its size field can
    # also truncate output silently. Decode ourselves with a bounded decoder.
    with archive.open(member):
        pass
    flags, method = struct.unpack_from("<HH", payload, member.header_offset + 6)
    if flags != member.flag_bits or method != member.compress_type:
        raise _ArchiveError("corrupt zip local header")
    name, extra = struct.unpack_from("<HH", payload, member.header_offset + 26)
    start = member.header_offset + 30 + name + extra
    raw = payload[start:start + member.compress_size]
    if len(raw) != member.compress_size:
        raise _ArchiveError("truncated zip member")
    if method == zipfile.ZIP_STORED:
        budget.consume(len(raw))
        result = raw
    else:
        result = _inflate(raw, "deflate" if method == zipfile.ZIP_DEFLATED else "bzip2",
                          budget, concatenated=False)
    if len(result) != member.file_size or zlib.crc32(result) != member.CRC:
        raise _ArchiveError("corrupt zip member size or checksum")
    return result


def _check_zip_directory(data: bytes, budget: _ArchiveBudget) -> None:
    """Bound central-directory allocations BEFORE ZipFile constructs ZipInfo objects."""
    import struct

    end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if end < 0 or end + 22 > len(data):
        raise _ArchiveError("corrupt zip directory")
    _, disk, start_disk, local_count, count, size, _, comment = struct.unpack_from("<4s4H2LH", data, end)
    if disk or start_disk or local_count != count or count == 65535 or size == 0xffffffff:
        raise _ArchiveError("unsupported multi-disk or ZIP64 directory")
    if end + 22 + comment != len(data) or size > end:
        raise _ArchiveError("corrupt zip directory")
    offset, seen = end - size, 0
    while offset < end:
        if data[offset:offset + 4] != b"PK\x01\x02" or offset + 46 > end:
            raise _ArchiveError("corrupt zip directory")
        budget.member()
        seen += 1
        name, extra, comment = struct.unpack_from("<3H", data, offset + 28)
        offset += 46 + name + extra + comment
    if offset != end or seen != count:
        raise _ArchiveError("corrupt zip directory")


def scan_archive(data: bytes, path: str, rules: list[tuple[str, str]]) -> list[str]:
    """Scan content-detected archives, recursively, with one budget per Git blob."""
    import io
    import tarfile
    import zipfile

    budget = _ArchiveBudget()
    found: list[str] = []

    def text(data: bytes, origin: str) -> None:
        found.extend(publication_secrets.archive_findings(data.decode("utf-8", "replace"), origin, rules))

    def visit(payload: bytes, origin: str, depth: int) -> None:
        kind = _archive_kind(payload)
        if kind is None:
            text(payload, origin)
            return
        inner = origin
        try:
            if depth >= ARCHIVE_MAX_DEPTH:
                raise _ArchiveError("archive nesting depth limit exceeded")
            if len(payload) > ARCHIVE_MAX_INPUT_BYTES:
                raise _ArchiveError("archive input byte limit exceeded")
            if kind in ("gzip", "bzip2", "xz"):
                inner = f"{origin}!<{kind}>"
                decoded = _inflate(payload, kind, budget, metadata=lambda value: text(value, inner + " (metadata)"))
                visit(decoded, inner, depth + 1)
            elif kind == "zip":
                _check_zip_directory(payload, budget)
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    text(archive.comment, origin + "!<comment>")
                    for member in archive.infolist():
                        inner = f"{origin}!{member.filename}"
                        text(member.filename.encode("utf-8"), inner + " (path)")
                        text(member.comment + member.extra, inner + " (metadata)")
                        if member.flag_bits & 1:
                            raise _ArchiveError("encrypted zip member")
                        # ZIP_LZMA has no dictionary-memory limit in ZipExtFile.
                        if member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2):
                            raise _ArchiveError("unsupported zip compression method")
                        if member.file_size > budget.remaining:
                            raise _ArchiveError("decompressed byte limit exceeded")
                        visit(_zip_payload(payload, archive, member, budget), inner, depth + 1)
            else:
                if len(payload) % 512 or payload[-1024:] != bytes(1024):
                    raise _ArchiveError("corrupt or truncated tar archive")

                class BoundedTarInfo(tarfile.TarInfo):
                    @classmethod
                    def fromtarfile(cls, archive):
                        return cls._fromtarfile(archive)

                    @classmethod
                    def _fromtarfile(cls, archive, *, dircheck=True):
                        # Extension headers recurse through this entry point on
                        # both older Python and security-patched tarfile builds.
                        buf = archive.fileobj.read(512)
                        try:
                            item = cls.frombuf(buf, archive.encoding, archive.errors)
                        except (tarfile.EOFHeaderError, tarfile.EmptyHeaderError):
                            raise
                        except tarfile.HeaderError:
                            raise _ArchiveError("corrupt tar header") from None
                        budget.member()  # Includes PAX and GNU extension headers.
                        if item.size < 0:
                            raise _ArchiveError("invalid tar member size")
                        if item.type in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME,
                                         tarfile.GNUTYPE_LONGLINK) and item.size > _CHUNK:
                            raise _ArchiveError("tar metadata byte limit exceeded")
                        item.offset = archive.fileobj.tell() - 512
                        return item._proc_member(archive)

                with tarfile.open(fileobj=io.BytesIO(payload), mode="r:", tarinfo=BoundedTarInfo,
                                  ignore_zeros=True) as archive:
                    for member in archive:
                        inner = f"{origin}!{member.name}"
                        metadata = "\n".join((member.name, member.linkname, member.uname, member.gname,
                                              *member.pax_headers.keys(), *member.pax_headers.values()))
                        encoded = metadata.encode("utf-8", "replace")
                        # Global PAX metadata is copied onto later members.
                        # Charge each copy before retaining more TarInfo objects.
                        budget.consume(len(encoded))
                        text(encoded, inner + " (metadata)")
                        if member.isreg() or member.type not in tarfile.SUPPORTED_TYPES:
                            if member.size > budget.remaining:
                                raise _ArchiveError("decompressed byte limit exceeded")
                            with archive.extractfile(member) as stream:
                                visit(budget.read(stream), inner, depth + 1)
        except Exception as error:
            # Library exceptions can quote member names or secret payload. Never echo them.
            reason = str(error) if isinstance(error, _ArchiveError) else "corrupt or unreadable archive"
            found.append(publication_secrets.archive_safe_text(f"{inner}: {reason}", rules))

    if _archive_kind(data) is not None:
        visit(data, path, 0)
    return found


def _scan_archive_blob(repo: str | Path, revision: str, path: str, rules: list[tuple[str, str]]) -> list[str]:
    """Inspect a small prefix first; read archive bytes with a fixed input bound."""
    with subprocess.Popen(["git", "-C", str(repo), "cat-file", "blob", f"{revision}:{path}"],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        try:
            prefix = process.stdout.read(1024)
            if _archive_kind(prefix) is None:
                return []
            data = prefix + process.stdout.read(max(0, ARCHIVE_MAX_INPUT_BYTES + 1 - len(prefix)))
            if len(data) > ARCHIVE_MAX_INPUT_BYTES:
                return [publication_secrets.archive_safe_text(f"{path}: archive input byte limit exceeded", rules)]
            if process.wait() != 0:
                raise RuntimeError("publish guard: git cat-file failed")
            return scan_archive(data, path, rules)
        finally:
            # A plain or oversized blob may still be writing to the pipe.
            if process.poll() is None:
                process.kill()


class _RulePath(Path):
    """Keep the caller's repo through the existing load_rules(list_path(repo)) API.

    An explicit list override can live anywhere, so its parent cannot identify the
    project. Per-value context avoids global state and cross-project races.
    """
    def __init__(self, *args, repo: str | Path | None = None):
        super().__init__(*args)
        self.repo = Path(repo).resolve() if repo is not None else None


def list_path(repo: str | Path | None = None) -> Path:
    """Explicit env override, else `data/secrets/` of the main checkout of `repo`
    (worktrees have no `data/`), else of this installation."""
    override = os.environ.get(ENV_VAR)
    if override:
        return _RulePath(override, repo=repo)
    candidates = []
    if repo is not None:
        common = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True,
        )
        if common.returncode == 0 and common.stdout.strip():
            candidates.append(Path(common.stdout.strip()).parent / REL_PATH)
    candidates.append(Path(__file__).resolve().parents[1] / REL_PATH)
    return _RulePath(next((c for c in candidates if c.is_file()), candidates[-1]), repo=repo)


def load_rules(path: Path) -> list[tuple[str, str]]:
    """List entries plus local credentials when path came from list_path(repo).

    secret_scan's existing pre-push call uses exactly this API. A missing stop-list
    must not skip credentials; a plain explicit Path keeps its list-only semantics.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    rules = [
        (f"forbidden-string line {n} of {path.name}", s)
        for n, raw in enumerate(lines, 1)
        if (s := raw.strip()) and not s.startswith("#")
    ]
    repo = getattr(path, "repo", None)
    if repo is not None:
        rules += publication_secrets.literal_rules(repo)
    return list(dict.fromkeys(rules))


def scan_text(text: str, origin: str, rules: list[tuple[str, str]]) -> list[str]:
    return publication_secrets.findings(text, origin, rules)


def scan_patch(patch: str, rules: list[tuple[str, str]]) -> list[str]:
    """Scan added text with destination line numbers, including binary blobs as text."""
    import ast
    import re

    found = []
    path, number, start = "?", 0, 0
    old_left, new_left = 0, 0
    added: list[str] = []

    def flush() -> None:
        found.extend(publication_secrets.content_findings("\n".join(added), path, rules, start))
        added.clear()

    for line in patch.split("\n"):
        # Hunk counts distinguish file headers from added text beginning with ++.
        if old_left or new_left:
            if line.startswith("+"):
                if not added:
                    start = number
                added.append(line[1:])
                number += 1
                new_left -= 1
            elif line.startswith("-"):
                flush()
                old_left -= 1
            elif line.startswith(" "):
                flush()
                number += 1
                new_left -= 1
                old_left -= 1
            continue
        if line.startswith("+++ "):
            flush()
            raw = line[4:]
            path = (ast.literal_eval(raw) if raw.startswith('"') else raw).removeprefix("b/")
            found += scan_text(path, f"{path}:1 (path)", rules)
        elif line.startswith("@@ "):
            flush()
            match = re.match(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if not match:
                raise RuntimeError("publish guard: malformed git diff hunk")
            old_left = int(match[1]) if match[1] is not None else 1
            number = int(match[2])
            new_left = int(match[3]) if match[3] is not None else 1
    flush()
    return found


def scan_range(repo: str | Path, base: str, head: str, rules: list[tuple[str, str]]) -> list[str]:
    """Findings in what `base..head` would publish: commit messages, paths and ADDED lines.
    Removed lines are ignored — deleting a leak must not be blocked."""
    rules = list(dict.fromkeys(rules + publication_secrets.literal_rules(repo)))

    def git(*args: str) -> str:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
        if done.returncode:
            # Git diagnostics may quote a secret-bearing path or commit message.
            raise RuntimeError(f"publish guard: git {args[0]} failed")
        return done.stdout.decode("utf-8", "replace")

    empty = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    if base != empty:
        merge_base = subprocess.run(
            ["git", "-C", str(repo), "merge-base", base, head], capture_output=True,
        )
        if merge_base.returncode not in (0, 1):
            raise RuntimeError("git merge-base failed")
    revisions = (head,) if base == empty else (head, f"^{base}")
    found = []
    # Every introduced commit matters: a later deletion does not remove its secret
    # from published history. Root and merge commits also need their own patches.
    for commit in git("rev-list", *revisions).splitlines():
        message = git("show", "-s", "--format=%B", commit)
        found += publication_secrets.content_findings(message, f"commit {commit} message", rules)
        # Empty files and mode-only changes have no +++ header in a patch.
        for path in git("diff-tree", "--root", "--no-commit-id", "-r", "-m", "--no-renames",
                        "--name-only", "--diff-filter=ACMT", "-z", commit).split("\0"):
            if path:
                found += scan_text(path, f"{path}:1 (path)", rules)
                # Patches decode binary bytes lossily. Read the new blob at EACH
                # introduced commit, excluding deletions as in the text scanner.
                archive_found = _scan_archive_blob(repo, commit, path, rules)
                found += archive_found
                if archive_found:
                    # Refusal is final. In particular, do not materialize an
                    # oversized archive again as a potentially huge --text diff.
                    return list(dict.fromkeys(found))
        patch = git("show", "--format=", "--root", "--diff-merges=separate",
                    "--no-ext-diff", "--no-textconv", "--no-renames", "--text", "-U0", commit)
        found += scan_patch(patch, rules)
    return list(dict.fromkeys(found))


def block_message(findings: list[str]) -> str:
    return (
        "PUBLISH GUARD: publication contains a local credential or forbidden string:\n  "
        + "\n  ".join(findings)
        + "\nMove the artifact to .orchestra/private/ or remove the string, then retry."
    )
