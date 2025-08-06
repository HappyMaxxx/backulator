import os
import tarfile
from pathlib import Path
import json
from datetime import datetime
import re
from rich.progress import Progress, BarColumn, TextColumn
from rich.console import Group
from rich.live import Live

SCRIPT_DIR = Path(__file__).resolve().parent
IGNORE_FILE = SCRIPT_DIR / ".backupignore"
METADATA_FILE = SCRIPT_DIR / "backup_metadata.json"

def load_ignore_list():
    ignore = set()
    if IGNORE_FILE.exists():
        with open(IGNORE_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    # Convert .backupignore patterns to regex
                    pattern = re.escape(line).replace(r'\*', '.*').replace(r'\?', '.')
                    ignore.add(pattern)
    return ignore

def should_ignore(path, ignore_patterns):
    rel_path = str(path)
    for pattern in ignore_patterns:
        if re.match(pattern, rel_path) or re.match(pattern, rel_path + '/.*'):
            return True
    return False

def load_metadata():
    if METADATA_FILE.exists():
        with open(METADATA_FILE, "r") as f:
            return json.load(f)
    return {}

def get_backup_files(backup_dir):
    backup_files = []
    for f in backup_dir.iterdir():
        if f.is_file() and f.name.startswith("home-backup-") and f.name.endswith(".tar.gz"):
            match = re.match(r"home-backup-.*-(full|incremental)-(\d{8}_\d{6})\.tar\.gz", f.name)
            if match:
                backup_type, timestamp = match.groups()
                try:
                    dt = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
                    backup_files.append((f, backup_type, dt))
                except ValueError:
                    continue
    return sorted(backup_files, key=lambda x: x[2])  # Sort by timestamp

def restore_incrementals(backup_dir, dest_dir):
    backup_dir = Path(backup_dir).resolve()
    dest_dir = Path(dest_dir).resolve()
    ignore_patterns = load_ignore_list()
    metadata = load_metadata()
    backup_files = get_backup_files(backup_dir)

    if not backup_files:
        print("❌ No valid backup files found in the specified directory.")
        return

    print(f"\n🔍 Found {len(backup_files)} backup archives.")
    for f, backup_type, dt in backup_files:
        print(f" - {f.name} ({backup_type}, {dt.strftime('%Y-%m-%d %H:%M:%S')})")

    confirm = input("\nProceed with restore? [Y/n]: ")
    if confirm.strip().lower() not in ["", "y", "yes"]:
        print("❌ Restore cancelled.")
        return

    processed_files = set()  # Track files that have been restored
    latest_mtime = {}  # Track the latest mtime for each file

    # Initialize progress bars
    main_progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        TextColumn("{task.completed}/{task.total} files"),
        transient=False
    )

    with Live(main_progress, refresh_per_second=10):
        total_files = 0
        # First pass: count total files for progress bar
        for backup_file, _, _ in backup_files:
            with tarfile.open(backup_file, "r:gz") as tar:
                total_files += sum(1 for member in tar if member.isfile() and not should_ignore(member.name, ignore_patterns))

        task = main_progress.add_task("Restoring backups...", total=total_files)

        for backup_file, backup_type, _ in backup_files:
            print(f"\n📦 Processing {backup_file.name} ({backup_type})...")
            with tarfile.open(backup_file, "r:gz") as tar:
                for member in tar:
                    if not member.isfile():
                        continue

                    if should_ignore(member.name, ignore_patterns):
                        print(f"⏭️ Skipping ignored file: {member.name}")
                        continue

                    dest_path = dest_dir / member.name
                    rel_path = member.name

                    # Check metadata status
                    file_metadata = metadata.get(rel_path, {})
                    file_mtime = member.mtime
                    stored_mtime = latest_mtime.get(rel_path, 0)
                    file_status = file_metadata.get("status", "present")

                    # Skip if the file is marked as deleted or ignored in metadata with a newer mtime
                    if file_status in ["deleted", "ignored"] and file_metadata.get("mtime", 0) >= file_mtime:
                        print(f"⏭️ Skipping {rel_path} (status: {file_status})")
                        continue

                    if rel_path not in processed_files or file_mtime > stored_mtime:
                        try:
                            # Ensure parent directories exist
                            dest_path.parent.mkdir(parents=True, exist_ok=True)

                            # Extract file only if status is present
                            if file_status == "present":
                                tar.extract(member, path=dest_dir)
                                print(f"✅ Restored: {rel_path}")

                            # Update tracking
                            processed_files.add(rel_path)
                            latest_mtime[rel_path] = file_mtime

                            main_progress.update(task, advance=1)

                        except Exception as e:
                            print(f"❗ Failed to restore {rel_path}: {e}")

    print(f"\n✅ Restore complete! Restored {len(processed_files)} files to {dest_dir}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Restore incremental backups.")
    parser.add_argument("--backup-dir", type=Path, required=True, help="Directory containing incremental backups")
    parser.add_argument("--dest", type=Path, required=True, help="Directory to restore into")
    args = parser.parse_args()
    restore_incrementals(args.backup_dir, args.dest)