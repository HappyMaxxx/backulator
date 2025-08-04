import os
import tarfile
import subprocess
import hashlib
import json
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.progress import Progress, BarColumn, TextColumn, ProgressColumn
from rich.text import Text
import sys
import argparse

HOME_DIR = Path.home()
SCRIPT_DIR = Path(__file__).resolve().parent
IGNORE_FILE = SCRIPT_DIR / ".backupignore"
METADATA_FILE = SCRIPT_DIR / "backup_metadata.json"

class FileCounterColumn(ProgressColumn):
    def render(self, task):
        return Text(f"{int(task.completed)}/{int(task.total)} files")

def get_mount_points():
    possible_mount_dirs = [
        f"/media/{os.getlogin()}",
        "/media",
        f"/run/media/{os.getlogin()}",
        "/mnt"
    ]

    mount_points = set()
    result = subprocess.run(["lsblk", "-o", "NAME,MOUNTPOINT"], capture_output=True, text=True)
    lines = result.stdout.strip().split('\n')[1:]

    for line in lines:
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            mountpoint = parts[1]
            for base in possible_mount_dirs:
                if mountpoint.startswith(base):
                    mount_points.add(mountpoint)

    return sorted(mount_points)

def ask_user_path(mount_points):
    if mount_points:
        print("Devices found:")
        for i, mp in enumerate(mount_points):
            print(f"[{i + 1}] {mp}")
        choice = input("Select the flash drive number or press Enter to cancel: ")
        if choice.strip().isdigit():
            idx = int(choice.strip()) - 1
            if 0 <= idx < len(mount_points):
                return Path(mount_points[idx])
    print("No flash drive found or selected.")
    confirm = input("The backup will be saved in your home directory. Continue? [y/N]: ")
    if confirm.lower().startswith("y"):
        return HOME_DIR
    else:
        print("Cancelled.")
        exit(0)

def load_ignore_list():
    ignore = set()
    if IGNORE_FILE.exists():
        with open(IGNORE_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ignore.add(line)
    return ignore

def should_ignore(path, ignore_set):
    rel_path = os.path.relpath(path, HOME_DIR)
    for pattern in ignore_set:
        if rel_path.startswith(pattern):
            return True
    return False

def calculate_file_hash(file_path):
    """Calculate SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (IOError, PermissionError):
        return None

def load_metadata():
    """Load previous backup metadata."""
    if METADATA_FILE.exists():
        with open(METADATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_metadata(metadata):
    """Save backup metadata."""
    with open(METADATA_FILE, "w") as f:
        json.dump(metadata, f, indent=4)

def collect_files_for_backup(ignore_set, incremental=False, max_workers=8):
    """Collect files for backup, optionally checking for changes."""
    all_files = []
    metadata = load_metadata() if incremental else {}

    def walk_dir(start_path):
        result = []
        for root, dirs, files in os.walk(start_path):
            root_path = Path(root)
            if should_ignore(root_path, ignore_set):
                dirs[:] = []  # Skip ignored directories
                continue
            for name in files:
                full_path = root_path / name
                if not should_ignore(full_path, ignore_set):
                    rel = os.path.relpath(full_path, HOME_DIR)
                    if incremental:
                        try:
                            mtime = os.path.getmtime(full_path)
                            file_hash = calculate_file_hash(full_path)
                            prev_metadata = metadata.get(rel, {})
                            if file_hash and (prev_metadata.get("hash") != file_hash or prev_metadata.get("mtime") != mtime):
                                result.append((str(full_path), rel, mtime, file_hash))
                        except (OSError, PermissionError):
                            continue
                    else:
                        result.append((str(full_path), rel, None, None))
        return result

    for item in HOME_DIR.iterdir():
        if item.is_file() and not should_ignore(item, ignore_set):
            rel = os.path.relpath(item, HOME_DIR)
            if incremental:
                try:
                    mtime = os.path.getmtime(item)
                    file_hash = calculate_file_hash(item)
                    prev_metadata = metadata.get(rel, {})
                    if file_hash and (prev_metadata.get("hash") != file_hash or prev_metadata.get("mtime") != mtime):
                        all_files.append((str(item), rel, mtime, file_hash))
                except (OSError, PermissionError):
                    continue
            else:
                all_files.append((str(item), rel, None, None))

    subdirs = [d for d in HOME_DIR.iterdir() if d.is_dir()]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(walk_dir, d) for d in subdirs]
        for f in as_completed(futures):
            all_files.extend(f.result())

    return all_files

def safe_unmount(path):
    try:
        subprocess.run(["umount", str(path)], check=True)
        print(f"\n✅ Unmounted {path}")
    except subprocess.CalledProcessError as e:
        print(f"\n❗ Failed to unmount {path}: {e}")

def create_backup(dest_dir, incremental=False):
    now = datetime.now()
    backup_type = "incremental" if incremental else "full"
    archive_name = f"home-backup-{Path().cwd().name}-{backup_type}-{now.strftime('%Y%m%d_%H%M%S')}.tar.gz"
    archive_path = dest_dir / archive_name
    ignore_set = load_ignore_list()

    print(f"🔍 Scanning files for {backup_type} backup (with .backupignore)...")
    all_files = collect_files_for_backup(ignore_set, incremental)
    total_files = len(all_files)
    estimated_time = round(max(3, total_files * 0.02))

    print(f"\n📦 Files to backup: {total_files}")
    print(f"⏱️  Estimated time: {estimated_time} seconds")
    preview = min(15, total_files)
    print("📄 Sample files:")
    for i in range(preview):
        print(f" - {all_files[i][1]}")
    if total_files > preview:
        print(f"...and {total_files - preview} more files.\n")

    confirm = input("Proceed with backup? [Y/n]: ")
    if confirm.strip().lower() not in ["", "y", "yes"]:
        print("❌ Cancelled.")
        exit(0)

    print(f"\n🔐 Creating {backup_type} archive: {archive_path}\n")

    new_metadata = {}
    try:
        with tarfile.open(archive_path, "w:gz") as tar, \
             Progress(
                 TextColumn("[progress.description]{task.description}"),
                 BarColumn(),
                 "[progress.percentage]{task.percentage:>3.0f}%",
                 FileCounterColumn(),
             ) as progress:

            task = progress.add_task("Backing up...", total=total_files)

            for file_data in all_files:
                full_path, rel, mtime, file_hash = file_data
                try:
                    print(f"Adding: {rel}")
                    tar.add(full_path, arcname=rel)
                    if incremental:
                        new_metadata[rel] = {"mtime": mtime, "hash": file_hash}
                except Exception as e:
                    print(f"❗ Failed to add {rel}: {e}")
                progress.advance(task)

        if incremental:
            # Update metadata with new files
            existing_metadata = load_metadata()
            existing_metadata.update(new_metadata)
            save_metadata(existing_metadata)

    except KeyboardInterrupt:
        print("\n⚠️ Backup interrupted by user (Ctrl+C).")
        if 'tar' in locals():
            tar.close()
        safe_unmount(dest_dir)
        print(f"✅ Partial archive saved: {archive_path}")
        sys.exit(0)
    except Exception as e:
        print(f"❗ Error during backup: {e}")
        if 'tar' in locals():
            tar.close()
        sys.exit(1)

    print(f"\n✅ {backup_type.capitalize()} backup complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create full or incremental backups.")
    parser.add_argument("--incremental", action="store_true", help="Perform an incremental backup")
    args = parser.parse_args()

    print()
    mount_points = get_mount_points()
    dest = ask_user_path(mount_points)
    create_backup(dest, args.incremental)
    safe_unmount(dest)