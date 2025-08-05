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
from rich.live import Live
from rich.console import Group
import sys
import argparse

HOME_DIR = Path.home()
SCRIPT_DIR = Path(__file__).resolve().parent
IGNORE_FILE = SCRIPT_DIR / ".backupignore"
METADATA_FILE = SCRIPT_DIR / "backup_metadata.json"
LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10 MB

class FileCounterColumn(ProgressColumn):
    def render(self, task):
        return Text(f"{int(task.completed)}/{int(task.total)} files")

class SizeProgressColumn(ProgressColumn):
    def render(self, task):
        completed_mb = task.completed / (1024 * 1024)
        total_mb = task.total / (1024 * 1024) if task.total else 0
        return Text(f"{completed_mb:.2f}/{total_mb:.2f} MB")

class LargeFileProgressColumn(ProgressColumn):
    def render(self, task):
        completed_mb = task.completed / (1024 * 1024)
        total_mb = task.total / (1024 * 1024) if task.total else 0
        return Text(f"File: {completed_mb:.2f}/{total_mb:.2f} MB")

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
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (IOError, PermissionError):
        return None

def load_metadata():
    if METADATA_FILE.exists():
        with open(METADATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_metadata(metadata):
    with open(METADATA_FILE, "w") as f:
        json.dump(metadata, f, indent=4)

def collect_files_for_backup(ignore_set, incremental=False, max_workers=10):
    all_files = []
    metadata = load_metadata() if incremental else {}

    def walk_dir(start_path):
        result = []
        for root, dirs, files in os.walk(start_path):
            root_path = Path(root)
            if should_ignore(root_path, ignore_set):
                dirs[:] = []
                continue
            for name in files:
                full_path = root_path / name
                if not should_ignore(full_path, ignore_set):
                    rel = os.path.relpath(full_path, HOME_DIR)
                    try:
                        size = os.path.getsize(full_path)
                        if incremental:
                            mtime = os.path.getmtime(full_path)
                            file_hash = calculate_file_hash(full_path)
                            prev_metadata = metadata.get(rel, {})
                            if file_hash and (prev_metadata.get("hash") != file_hash or prev_metadata.get("mtime") != mtime):
                                result.append((str(full_path), rel, mtime, file_hash, size))
                        else:
                            result.append((str(full_path), rel, None, None, size))
                    except (OSError, PermissionError):
                        continue
        return result

    for item in HOME_DIR.iterdir():
        if item.is_file() and not should_ignore(item, ignore_set):
            rel = os.path.relpath(item, HOME_DIR)
            try:
                size = os.path.getsize(item)
                if incremental:
                    mtime = os.path.getmtime(item)
                    file_hash = calculate_file_hash(item)
                    prev_metadata = metadata.get(rel, {})
                    if file_hash and (prev_metadata.get("hash") != file_hash or prev_metadata.get("mtime") != mtime):
                        all_files.append((str(item), rel, mtime, file_hash, size))
                else:
                    all_files.append((str(item), rel, None, None, size))
            except (OSError, PermissionError):
                continue

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

def add_file_to_tar(tar, full_path, arcname, file_size, progress, large_file_task=None):
    tarinfo = tar.gettarinfo(full_path, arcname=arcname)
    tarinfo.mtime = os.path.getmtime(full_path)

    if file_size > LARGE_FILE_THRESHOLD and large_file_task is not None:
        progress.update(large_file_task, description=f"Adding {arcname}")
        with open(full_path, "rb") as f:
            bytes_written = 0
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                tar.fileobj.write(chunk)
                bytes_written += len(chunk)
                progress.update(large_file_task, advance=len(chunk))
        tar.offset += tarinfo.size
    else:
        with open(full_path, "rb") as f:
            tar.addfile(tarinfo, fileobj=f)

def create_backup(dest_dir, incremental=False):
    now = datetime.now()
    backup_type = "incremental" if incremental else "full"
    archive_name = f"home-backup-{Path().cwd().name}-{backup_type}-{now.strftime('%Y%m%d_%H%M%S')}.tar.gz"
    archive_path = dest_dir / archive_name
    ignore_set = load_ignore_list()

    print(f"🔍 Scanning files for {backup_type} backup (with .backupignore)...")
    all_files = collect_files_for_backup(ignore_set, incremental)
    total_files = len(all_files)
    total_size = sum(file_data[4] for file_data in all_files)
    estimated_time = round(max(3, total_files * 0.02))

    print(f"\n📦 Files to backup: {total_files}")
    print(f"💾 Total size: {total_size / (1024 * 1024):.2f} MB")
    print(f"⏱️ Estimated time: {estimated_time} seconds")
    preview = min(15, total_files)
    print("📄 Sample files:")
    for i in range(preview):
        print(f" - {all_files[i][1]} ({all_files[i][4] / (1024 * 1024):.2f} MB)")
    if total_files > preview:
        print(f"...and {total_files - preview} more files.\n")

    confirm = input("Proceed with backup? [Y/n]: ")
    if confirm.strip().lower() not in ["", "y", "yes"]:
        print("❌ Cancelled.")
        exit(0)

    print(f"\n🔐 Creating {backup_type} archive: {archive_path}\n")

    new_metadata = {}

    main_progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        FileCounterColumn(),
        transient=False
    )

    large_file_progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        LargeFileProgressColumn(),
        transient=True
    )

    try:
        with tarfile.open(archive_path, "w:gz") as tar, \
             Live(Group(main_progress, large_file_progress), refresh_per_second=10):

            task = main_progress.add_task("Creating backup...", total=total_files)
            large_file_task = large_file_progress.add_task("Adding large file...", total=0, visible=False)

            for file_data in all_files:
                full_path, rel, mtime, file_hash, size = file_data
                try:
                    if size > LARGE_FILE_THRESHOLD:
                        large_file_progress.update(
                            large_file_task,
                            completed=0,
                            total=size,
                            description=f"[cyan]Adding {rel}",
                            visible=True
                        )
                        print(f"Adding large file: {rel} ({size / (1024 * 1024):.2f} MB)")
                    else:
                        large_file_progress.update(large_file_task, visible=False)
                        print(f"Adding: {rel} ({size / (1024 * 1024):.2f} MB)")

                    add_file_to_tar(tar, full_path, rel, size, large_file_progress, large_file_task)

                    if incremental:
                        new_metadata[rel] = {"mtime": mtime, "hash": file_hash}

                    main_progress.update(task, advance=1)

                except Exception as e:
                    print(f"❗ Failed to add {rel}: {e}")
                finally:
                    large_file_progress.update(large_file_task, visible=False)

        if incremental:
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
