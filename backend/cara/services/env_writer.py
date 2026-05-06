"""Atomic mutation of the dotenv file at /opt/cara/.env from inside the
running backend container.

Reads, mutates, writes back atomically — preserves comments, blank
lines, and surrounding key order. The CARA backend runs uvicorn in a
docker container with `/opt/cara/.env` bind-mounted at `/app/.env` (or
loaded by pydantic-settings at startup). After a write, the backend
needs a `docker restart cara-backend` for pydantic-settings to pick up
the new values. The setup endpoints surface a banner asking the admin
to restart at the end of the wizard.

NEVER log raw values: secrets pass through here. Audit logs upstream
should hash with `mask_secret()`.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


# Default path inside the container — bind-mounted from /opt/cara/.env
# on the host. Override via CARA_ENV_FILE for tests / non-default
# deployments.
DEFAULT_ENV_PATH = Path(os.environ.get("CARA_ENV_FILE", "/app/.env"))


_ASSIGN_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=")


def _quote(value: str) -> str:
    """Return `value` properly quoted for dotenv. Keeps existing
    behaviour: single-line values without `"` or `\\` are unquoted;
    everything else gets double-quoted with escaping."""
    if not value:
        return ""
    needs_quote = any(c in value for c in (" ", "\t", "#", "'", "$"))
    if not needs_quote and "\n" not in value and '"' not in value and "\\" not in value:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def mask_secret(value: str | None) -> str:
    """Return `***hash:<sha256[:8]>***` for safe audit logging."""
    if not value:
        return "<empty>"
    h = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"***hash:{h}***"


def read_env(path: Path | None = None) -> dict[str, str]:
    """Parse the .env file. Returns {key: raw_value} (unquoted). Lines
    that don't match KEY=VALUE are skipped silently. Missing file → {}."""
    p = path or DEFAULT_ENV_PATH
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _ASSIGN_RE.match(line)
        if not m:
            continue
        key = m.group(1)
        rhs = line[m.end():].strip()
        # Strip optional trailing comment
        if rhs.startswith('"'):
            # Quoted — find matching end-quote, allowing escaped \"
            i = 1
            while i < len(rhs):
                if rhs[i] == "\\":
                    i += 2
                    continue
                if rhs[i] == '"':
                    break
                i += 1
            value = rhs[1:i]
            value = value.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")
        else:
            # Unquoted — terminate at # comment marker (if any)
            hash_idx = rhs.find("#")
            value = rhs if hash_idx == -1 else rhs[:hash_idx].rstrip()
        out[key] = value
    return out


def write_env(
    updates: dict[str, str | None],
    *,
    path: Path | None = None,
) -> dict[str, str]:
    """Apply `updates` to the .env file in place, atomically.

    A None value DELETES the key. Existing KEY= lines are rewritten in
    place; new keys are appended at the end (preceded by a blank line if
    the file didn't end with one). Comments and unrelated lines are
    preserved verbatim.

    Returns the resulting full {key: value} dict (after the merge) so
    the caller can verify what was written.
    """
    p = path or DEFAULT_ENV_PATH
    p.parent.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []
    if p.exists():
        existing_lines = p.read_text(encoding="utf-8").splitlines(keepends=True)

    # Track which keys we've already rewritten so we can append the rest.
    pending = dict(updates)
    out_lines: list[str] = []

    for raw_line in existing_lines:
        stripped = raw_line.lstrip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(raw_line)
            continue
        m = _ASSIGN_RE.match(raw_line)
        if not m:
            out_lines.append(raw_line)
            continue
        key = m.group(1)
        if key in pending:
            new_val = pending.pop(key)
            if new_val is None:
                # Delete: skip the line entirely
                continue
            line_end = "\n" if raw_line.endswith("\n") else ""
            out_lines.append(f"{key}={_quote(new_val)}{line_end}")
        else:
            out_lines.append(raw_line)

    # Append remaining new keys
    if pending:
        if out_lines and not out_lines[-1].endswith("\n"):
            out_lines.append("\n")
        if out_lines and out_lines[-1].strip():
            out_lines.append("\n")
        for key, value in pending.items():
            if value is None:
                continue
            out_lines.append(f"{key}={_quote(value)}\n")

    # Atomic write: write to .env.new, fsync, rename over .env
    fd, tmp_path = tempfile.mkstemp(prefix=".env.", dir=str(p.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(out_lines)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, p)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    log.info(
        "env.write",
        keys=sorted(updates.keys()),
        masked_values={k: mask_secret(v) for k, v in updates.items() if v is not None},
        deleted=[k for k, v in updates.items() if v is None],
        env_file=str(p),
    )

    return read_env(p)
