#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OWNER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


@dataclass(frozen=True)
class VerificationResult:
    checked_bundles: int
    checked_files: int
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def build_rsync_command(
    *,
    server: str,
    remote_root: str,
    local_vault: str,
    owner: str | None = None,
    ssh_port: int | None = None,
    ssh_key: str | None = None,
    dry_run: bool = False,
    prune: bool = False,
    verbose: bool = False,
) -> list[str]:
    effective_remote_root = owner_remote_root(remote_root, owner)
    remote = f"{server}:{effective_remote_root.rstrip('/')}/"
    local = str(Path(local_vault).expanduser()) + "/"
    cmd = [
        "rsync",
        "-az",
        "--partial",
        "--human-readable",
        "--stats",
        "--exclude",
        ".tmp/",
        "--exclude",
        "*/.tmp/",
    ]
    if verbose:
        cmd.append("--progress")
    if dry_run:
        cmd.append("--dry-run")
    if prune:
        cmd.append("--delete")
    ssh_transport = build_rsync_ssh_transport(ssh_port=ssh_port, ssh_key=ssh_key)
    if ssh_transport:
        cmd.extend(["-e", ssh_transport])
    cmd.extend([remote, local])
    return cmd


def build_rsync_ssh_transport(*, ssh_port: int | None = None, ssh_key: str | None = None) -> str:
    parts = ["ssh"]
    if ssh_port:
        parts.extend(["-p", str(ssh_port)])
    if ssh_key:
        parts.extend(["-i", shlex.quote(str(Path(ssh_key).expanduser())), "-o", "IdentitiesOnly=yes"])
    return " ".join(parts) if len(parts) > 1 else ""


def build_ssh_command_prefix(*, ssh_port: int | None = None, ssh_key: str | None = None) -> list[str]:
    cmd = ["ssh"]
    if ssh_port:
        cmd.extend(["-p", str(ssh_port)])
    if ssh_key:
        cmd.extend(["-i", str(Path(ssh_key).expanduser()), "-o", "IdentitiesOnly=yes"])
    return cmd


def validate_owner_id(owner: str) -> str:
    clean = owner.strip()
    if not OWNER_ID_RE.fullmatch(clean):
        raise ValueError("owner must match ^[a-z0-9][a-z0-9_-]{0,62}$")
    return clean


def owner_remote_root(remote_root: str, owner: str | None) -> str:
    if not owner:
        return remote_root
    return f"{remote_root.rstrip('/')}/users/{validate_owner_id(owner)}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_manifest_file_records(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    files = manifest.get("files", {})
    if isinstance(files, dict):
        for name, record in files.items():
            # Some backfilled manifests can contain a self-hash for manifest.json;
            # ignore it because writing that hash changes the manifest itself.
            if name == "manifest":
                continue
            if isinstance(record, dict):
                records.append(record)
    for collection_name in ("images", "videos"):
        collection = manifest.get(collection_name, [])
        if isinstance(collection, list):
            for record in collection:
                if isinstance(record, dict) and record.get("status") == "downloaded":
                    records.append(record)
    return records


def verify_local_bundle(bundle_dir: Path) -> VerificationResult:
    manifest_path = bundle_dir / "manifest.json"
    errors: list[str] = []
    checked_files = 0
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception as exc:
        return VerificationResult(checked_bundles=1, checked_files=0, errors=[f"{manifest_path}: cannot read manifest: {exc}"])

    for record in _iter_manifest_file_records(manifest):
        relative = record.get("path")
        expected_sha = record.get("sha256")
        if not relative or not expected_sha:
            continue
        target = (bundle_dir / str(relative)).resolve()
        try:
            target.relative_to(bundle_dir.resolve())
        except ValueError:
            errors.append(f"{bundle_dir}: unsafe manifest path {relative!r}")
            continue
        if not target.exists():
            errors.append(f"{bundle_dir}: missing {relative}")
            continue
        checked_files += 1
        actual_sha = _sha256_file(target)
        if actual_sha != expected_sha:
            errors.append(f"{bundle_dir}: sha256 mismatch for {relative}: expected {expected_sha}, got {actual_sha}")
    return VerificationResult(checked_bundles=1, checked_files=checked_files, errors=errors)


def verify_local_vault(local_vault: str | Path) -> VerificationResult:
    root = Path(local_vault).expanduser()
    errors: list[str] = []
    checked_bundles = 0
    checked_files = 0
    for manifest_path in sorted((root / "posts").glob("*/*/*/*/manifest.json")):
        result = verify_local_bundle(manifest_path.parent)
        checked_bundles += result.checked_bundles
        checked_files += result.checked_files
        errors.extend(result.errors)
    return VerificationResult(checked_bundles=checked_bundles, checked_files=checked_files, errors=errors)


REMOTE_PRUNE_SCRIPT = r'''
from __future__ import annotations
import argparse
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", required=True)
parser.add_argument("--days", required=True, type=int)
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

root = Path(args.root).expanduser().resolve()
posts = root / "posts"
cutoff = date.today() - timedelta(days=args.days)
results = []

if not posts.exists():
    print(json.dumps({"root": str(root), "deleted": 0, "candidates": 0, "results": [], "note": "posts directory missing"}, ensure_ascii=False))
    raise SystemExit(0)

for bundle in sorted(posts.glob("*/*/*/*")):
    if not bundle.is_dir():
        continue
    try:
        rel = bundle.relative_to(posts)
        year, month, day, job_id = rel.parts[:4]
        bundle_date = date(int(year), int(month), int(day))
    except Exception:
        continue
    if bundle_date >= cutoff:
        continue
    item = {"path": str(bundle), "date": bundle_date.isoformat(), "job_id": job_id, "deleted": False}
    if not args.dry_run:
        shutil.rmtree(bundle)
        item["deleted"] = True
    results.append(item)

# Remove now-empty day/month/year directories without touching non-empty dirs.
if not args.dry_run:
    for level in (3, 2, 1):
        for directory in sorted(posts.glob("/".join(["*"] * level)), reverse=True):
            if directory.is_dir():
                try:
                    directory.rmdir()
                except OSError:
                    pass

print(json.dumps({"root": str(root), "cache_days": args.days, "cutoff_exclusive": cutoff.isoformat(), "deleted": sum(1 for item in results if item["deleted"]), "candidates": len(results), "results": results}, ensure_ascii=False))
'''


def build_remote_prune_command(
    *,
    server: str,
    remote_root: str,
    days: int,
    owner: str | None = None,
    ssh_port: int | None = None,
    ssh_key: str | None = None,
    dry_run: bool = False,
    remote_sudo: bool = False,
) -> list[str]:
    cmd = build_ssh_command_prefix(ssh_port=ssh_port, ssh_key=ssh_key)
    cmd.append(server)
    if remote_sudo:
        cmd.append("sudo")
    cmd.extend(["python3", "-", "--root", owner_remote_root(remote_root, owner), "--days", str(days)])
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def run_remote_prune(
    *,
    server: str,
    remote_root: str,
    days: int,
    owner: str | None = None,
    ssh_port: int | None = None,
    ssh_key: str | None = None,
    dry_run: bool = False,
    remote_sudo: bool = False,
) -> int:
    cmd = build_remote_prune_command(
        server=server,
        remote_root=remote_root,
        days=days,
        owner=owner,
        ssh_port=ssh_port,
        ssh_key=ssh_key,
        dry_run=dry_run,
        remote_sudo=remote_sudo,
    )
    result = subprocess.run(cmd, input=REMOTE_PRUNE_SCRIPT, text=True, check=False)
    return result.returncode


def build_remote_rsync_check_command(*, server: str, ssh_port: int | None = None, ssh_key: str | None = None) -> list[str]:
    cmd = build_ssh_command_prefix(ssh_port=ssh_port, ssh_key=ssh_key)
    cmd.append(server)
    cmd.append("command -v rsync >/dev/null 2>&1")
    return cmd


def check_remote_rsync(*, server: str, ssh_port: int | None = None, ssh_key: str | None = None) -> int:
    result = subprocess.run(
        build_remote_rsync_check_command(server=server, ssh_port=ssh_port, ssh_key=ssh_key),
        check=False,
    )
    return result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync raw Rednote capture bundles from the server into a local permanent Obsidian raw vault."
    )
    parser.add_argument("--server", required=True, help="SSH target, for example user@example.com")
    parser.add_argument("--remote-root", default="/data/rednote_raw", help="Server host-visible raw storage root")
    parser.add_argument(
        "--owner",
        default=None,
        help="Optional owner id to sync, for example hongbin or zhangyu. Syncs remote-root/users/<owner>/ into the local vault.",
    )
    parser.add_argument(
        "--local-vault",
        default="~/Documents/raw_rednote_post_vault",
        help="Local permanent Obsidian raw vault directory",
    )
    parser.add_argument("--ssh-port", type=int, default=None, help="Optional SSH port")
    parser.add_argument("--ssh-key", default=None, help="Optional SSH private key or .pem path")
    parser.add_argument("--dry-run", action="store_true", help="Show planned sync/prune without writing or deleting files")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete local files that no longer exist on the server. Off by default; not recommended for a permanent local vault.",
    )
    parser.add_argument("--verbose", action="store_true", help="Show rsync progress details")
    parser.add_argument("--no-verify", action="store_true", help="Skip local manifest/hash verification after rsync")
    parser.add_argument(
        "--remote-cache-days",
        type=int,
        default=None,
        help="After a successful pull and local verification, delete server bundles older than this many days. Use 30 for one-month cache.",
    )
    parser.add_argument("--remote-prune-sudo", action="store_true", help="Run remote cache deletion through sudo")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        owner = validate_owner_id(args.owner) if args.owner else None
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    local_vault = Path(args.local_vault).expanduser()
    if not args.dry_run:
        local_vault.mkdir(parents=True, exist_ok=True)

    if args.prune:
        print("WARNING: --prune deletes local files missing on the server; this is usually wrong for a permanent local vault.", file=sys.stderr)

    remote_check = check_remote_rsync(server=args.server, ssh_port=args.ssh_port, ssh_key=args.ssh_key)
    if remote_check != 0:
        print(
            "Remote server does not have rsync installed or is not reachable. "
            f"Install it first, for example: ssh {args.server!r} 'apt-get update && apt-get install -y rsync'",
            file=sys.stderr,
        )
        return remote_check

    cmd = build_rsync_command(
        server=args.server,
        remote_root=args.remote_root,
        local_vault=str(local_vault),
        owner=owner,
        ssh_port=args.ssh_port,
        ssh_key=args.ssh_key,
        dry_run=args.dry_run,
        prune=args.prune,
        verbose=args.verbose,
    )
    rsync_result = subprocess.run(cmd, check=False)
    if rsync_result.returncode != 0:
        return rsync_result.returncode

    verification_ok = True
    if not args.dry_run and not args.no_verify:
        verification = verify_local_vault(local_vault)
        print(f"Verified local vault: bundles={verification.checked_bundles} files={verification.checked_files} errors={len(verification.errors)}")
        if verification.errors:
            verification_ok = False
            for error in verification.errors[:50]:
                print(f"VERIFY ERROR: {error}", file=sys.stderr)
            if len(verification.errors) > 50:
                print(f"VERIFY ERROR: ... {len(verification.errors) - 50} more", file=sys.stderr)

    if args.remote_cache_days is not None:
        if args.remote_cache_days < 1:
            print("--remote-cache-days must be >= 1", file=sys.stderr)
            return 2
        if args.no_verify and not args.dry_run:
            print("Refusing remote deletion with --no-verify. Remove --no-verify or run a dry-run.", file=sys.stderr)
            return 2
        if not verification_ok:
            print("Refusing remote deletion because local verification failed.", file=sys.stderr)
            return 2
        return run_remote_prune(
            server=args.server,
            remote_root=args.remote_root,
            days=args.remote_cache_days,
            owner=owner,
            ssh_port=args.ssh_port,
            ssh_key=args.ssh_key,
            dry_run=args.dry_run,
            remote_sudo=args.remote_prune_sudo,
        )

    return 0 if verification_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
