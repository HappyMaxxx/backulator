import os
import tarfile
import subprocess
import hashlib
import json
import shutil
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.progress import Progress, BarColumn, TextColumn, ProgressColumn
from rich.text import Text
from rich.live import Live
from rich.console import Group
from pyfiglet import Figlet
import logging
import sys
import re

from parse_args import parse_args
from restore_incremental import restore_incrementals

HOME_DIR = Path.home()
SCRIPT_DIR = Path(__file__).resolve().parent
IGNORE_FILE = SCRIPT_DIR / ".backupignore"
LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10 MB
f = Figlet(font='graffiti')

LOG_FILE = SCRIPT_DIR / "backup.log"

# Configure logging
try:
    logger = logging.getLogger("backup")
    logger.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.WARNING)  # консоль тільки для попереджень/помилок
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)
    logger.handlers = [file_handler, stream_handler]
except Exception as e:
    print(f"❗ Failed to initialize logging: {e}")
    sys.exit(1)

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

class ProgressFileReader:
    def __init__(self, file_obj, progress, task_id):
        self.file_obj = file_obj
        self.progress = progress
        self.task_id = task_id

    def read(self, size):
        data = self.file_obj.read(size)
        self.progress.update(self.task_id, advance=len(data))
        return data

    def close(self):
        self.file_obj.close()

def get_metadata_file(dest_dir):
    return Path(dest_dir) / "backup_metadata.json"

def get_mount_points():
    possible_mount_dirs = [
        f"/media/{os.getlogin()}",
        "/media",
        f"/run/media/{os.getlogin()}",
        "/mnt"
    ]

    mount_points = set()
    try:
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
    except subprocess.SubprocessError as e:
        logger.error(f"Failed to get mount points: {e}")
        return []

def ask_user_path(mount_points, silent=False):
    if silent:
        return Path(mount_points[0]) if mount_points else HOME_DIR

    if mount_points:
        print("Devices found:")
        for i, mp in enumerate(mount_points):
            print(f"[{i + 1}] {mp}")
        while True:
            choice = input("Select the flash drive number or press Enter to cancel: ")
            if not choice.strip():
                return None
            if choice.strip().isdigit() and 1 <= int(choice) <= len(mount_points):
                return Path(mount_points[int(choice) - 1])
            print("❗ Invalid input. Please enter a valid number.")

    print("No flash drive found or selected.")
    confirm = input("The backup will be saved in your home directory. Continue? [y/N]: ")
    if confirm.lower().startswith("y"):
        return HOME_DIR
    else:
        print("Cancelled.")
        exit(0)

def load_ignore_list():
    ignore = set()
    try:
        if IGNORE_FILE.exists():
            with open(IGNORE_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        pattern = re.escape(line).replace(r'\\*', '.*').replace(r'\\?', '.')
                        ignore.add(pattern)
        return ignore
    except Exception as e:
        logger.error(f"Failed to load ignore list: {e}")
        return set()

def should_ignore(path, ignore_patterns):
    rel_path = os.path.relpath(path, HOME_DIR)
    for pattern in ignore_patterns:
        if re.match(pattern, rel_path) or re.match(pattern, rel_path + '/.*'):
            return True
    return False

def calculate_file_hash(file_path):
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (IOError, PermissionError) as e:
        logger.error(f"Failed to calculate hash for {file_path}: {e}")
        return None

def load_metadata(dest_dir):
    metadata_file = get_metadata_file(dest_dir)
    try:
        if metadata_file.exists():
            with open(metadata_file, "r") as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Failed to load metadata: {e}")
        return {}

def save_metadata(metadata, dest_dir):
    metadata_file = get_metadata_file(dest_dir)
    try:
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save metadata: {e}")

def collect_files_for_backup(ignore_patterns, dest_dir, incremental=False, fast=False, max_workers=10):
    logger.info(f"Collecting files for backup, incremental={incremental}, fast={fast}")
    all_files = []
    deleted_files = []
    metadata = load_metadata(dest_dir) if incremental else {}
    existing_files = set(metadata.keys())

    def is_changed_fast(prev_meta, mtime_int, size):
        prev_mtime = int(prev_meta.get("mtime", 0)) if isinstance(prev_meta.get("mtime"), (int, float)) else 0
        if "hash" in prev_meta:
            return prev_mtime != mtime_int
        if "size" in prev_meta:
            return prev_mtime != mtime_int or prev_meta.get("size") != size
        return True

    def walk_dir(start_path):
        result = []
        try:
            for root, dirs, files in os.walk(start_path):
                root_path = Path(root)
                if should_ignore(root_path, ignore_patterns):
                    dirs[:] = []
                    continue
                for name in files:
                    full_path = root_path / name
                    if should_ignore(full_path, ignore_patterns):
                        continue
                    rel = os.path.relpath(full_path, HOME_DIR)
                    try:
                        size = os.path.getsize(full_path)
                        if incremental:
                            mtime_int = int(os.path.getmtime(full_path))
                            prev = metadata.get(rel, {})
                            if fast:
                                if is_changed_fast(prev, mtime_int, size):
                                    result.append((str(full_path), rel, mtime_int, None, size))
                            else:
                                file_hash = calculate_file_hash(full_path)
                                if file_hash and (prev.get("hash") != file_hash or int(prev.get("mtime", 0)) != mtime_int):
                                    result.append((str(full_path), rel, mtime_int, file_hash, size))
                            if rel in existing_files:
                                existing_files.remove(rel)
                        else:
                            result.append((str(full_path), rel, None, None, size))
                    except (OSError, PermissionError):
                        continue
            return result
        except Exception as e:
            logger.error(f"Error walking directory {start_path}: {e}")
            return []

    for item in HOME_DIR.iterdir():
        if item.is_file() and not should_ignore(item, ignore_patterns):
            rel = os.path.relpath(item, HOME_DIR)
            try:
                size = os.path.getsize(item)
                if incremental:
                    mtime_int = int(os.path.getmtime(item))
                    prev = metadata.get(rel, {})
                    if fast:
                        if is_changed_fast(prev, mtime_int, size):
                            all_files.append((str(item), rel, mtime_int, None, size))
                    else:
                        file_hash = calculate_file_hash(item)
                        if file_hash and (prev.get("hash") != file_hash or int(prev.get("mtime", 0)) != mtime_int):
                            all_files.append((str(item), rel, mtime_int, file_hash, size))
                    if rel in existing_files:
                        existing_files.remove(rel)
                else:
                    all_files.append((str(item), rel, None, None, size))
            except (OSError, PermissionError):
                continue

    subdirs = [d for d in HOME_DIR.iterdir() if d.is_dir()]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(walk_dir, d) for d in subdirs]
        for f in as_completed(futures):
            try:
                all_files.extend(f.result())
            except Exception as e:
                logger.error(f"Error in directory walk: {e}")

    if incremental:
        for rel in existing_files:
            if not should_ignore(Path(HOME_DIR) / rel, ignore_patterns):
                deleted_files.append(rel)

    logger.info(f"Collected {len(all_files)} files and {len(deleted_files)} deleted files for backup")
    return all_files, deleted_files

def safe_unmount(path):
    try:
        subprocess.run(["umount", str(path)], check=True)
        print(f"\n✅ Unmounted {path}")
    except subprocess.CalledProcessError as e:
        print(f"\n❗ Failed to unmount {path}: {e}")

def add_file_to_tar(tar, full_path, arcname, file_size, progress, large_file_task=None):
    try:
        tarinfo = tar.gettarinfo(full_path, arcname=arcname)
        tarinfo.mtime = os.path.getmtime(full_path)

        with open(full_path, "rb") as f:
            if file_size > LARGE_FILE_THRESHOLD and large_file_task is not None:
                progress.update(large_file_task, total=file_size, completed=0, description=f"Adding {arcname}", visible=True)
                wrapper = ProgressFileReader(f, progress, large_file_task)
                tar.addfile(tarinfo, fileobj=wrapper)
                progress.update(large_file_task, visible=False)
            else:
                tar.addfile(tarinfo, fileobj=f)
    except Exception as e:
        logger.error(f"Failed to add file to tar {arcname}: {e}")
        raise

def create_backup(dest_dir, incremental=False, silent=False, fast=False):
    now = datetime.now()
    backup_type = "incremental" if incremental else "full"
    archive_name = f"home-backup-{Path().cwd().name}-{backup_type}-{now.strftime('%Y%m%d_%H%M%S')}.tar.gz"
    archive_path = dest_dir / archive_name
    disk = shutil.disk_usage(dest_dir)
    ignore_patterns = load_ignore_list()

    try:
        all_files, deleted_files = collect_files_for_backup(ignore_patterns, dest_dir, incremental, fast)
    except KeyboardInterrupt:
        print("\n⚠️ Backup interrupted by user (Ctrl+C).")
        sys.exit(0)

    total_files = len(all_files)
    total_size = sum(file_data[4] for file_data in all_files)
    estimated_time = round(max(3, total_files * 0.02))
 
    if not silent:
        print(f"\n📦 Files to backup: {total_files}")
        if deleted_files:
            print(f"🗑️ Files to mark as deleted: {len(deleted_files)}")
        print(f"💾 Total size: {total_size / (1024 * 1024):.2f} MB")
        print(f"🖴 Free disk space: {disk.free / (1024 * 1024):.2f} MB")
        print(f"⏱️ Estimated time: {estimated_time} seconds")
        preview = min(15, total_files)
        print("📄 Sample files:")
        for i in range(preview):
            print(f" - {all_files[i][1]} ({all_files[i][4] / (1024 * 1024):.2f} MB)")
        if total_files > preview:
            print(f"...and {total_files - preview} more files.\n")
        if deleted_files:
            print("🗑️ Sample deleted files:")
            for i in range(min(5, len(deleted_files))):
                print(f" - {deleted_files[i]}")
            if len(deleted_files) > 5:
                print(f"...and {len(deleted_files) - 5} more deleted files.\n")

        confirm = input("Proceed with backup? [Y/n]: ")
        if confirm.strip().lower() not in ["", "y", "yes"]:
            print("❌ Cancelled.")
            exit(0)

    if disk.free < total_size * 1.1:
        print("❗ Not enough disk space!")
        exit(0)

    new_metadata = {}
    if incremental:
        existing_metadata = load_metadata(dest_dir)
        new_metadata = existing_metadata.copy()

    main_progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        FileCounterColumn(),
        transient=silent
    )

    large_file_progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        LargeFileProgressColumn(),
        transient=silent
    )

    try:
        with tarfile.open(archive_path, "w:gz") as tar, \
             Live(Group(main_progress, large_file_progress), refresh_per_second=10):

            task = main_progress.add_task("Creating backup...", total=total_files + len(deleted_files))
            large_file_task = large_file_progress.add_task("Adding large file...", total=0, visible=False)

            for file_data in all_files:
                full_path, rel, mtime, file_hash, size = file_data
                try:
                    if size > LARGE_FILE_THRESHOLD:
                        if not silent:
                            large_file_progress.update(
                                large_file_task,
                                completed=0,
                                total=size,
                                description=f"[cyan]Adding {rel}",
                                visible=True
                            )
                    else:
                        if not silent:
                            large_file_progress.update(large_file_task, visible=False)

                    add_file_to_tar(tar, full_path, rel, size, large_file_progress, large_file_task)

                    if incremental:
                        if fast:
                            new_metadata[rel] = {"mtime": mtime, "size": size, "status": "present"}
                        else:
                            new_metadata[rel] = {"mtime": mtime, "hash": file_hash, "status": "present"}

                    main_progress.update(task, advance=1)

                except Exception as e:
                    print(f"❗ Failed to add {rel}: {e}")
                finally:
                    if not silent:
                        large_file_progress.update(large_file_task, visible=False)

            if incremental and deleted_files:
                deletion_ts = int(datetime.now().timestamp())
                for rel in deleted_files:
                    new_metadata[rel] = {"status": "deleted", "mtime": deletion_ts}
                    if not silent:
                        main_progress.update(task, advance=1)


        save_metadata(new_metadata, dest_dir)
        if not silent:
            print(f"\n✅ {backup_type.capitalize()} backup complete!")

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
        safe_unmount(dest_dir)
        sys.exit(1)

if __name__ == "__main__":
    args = parse_args()

    if not args.silent:
        print()
        print(f.renderText('Backulator'))
    if args.restore:
        if not args.backup_dir or not args.dest:
            print("❌ --backup-dir and --dest must be provided for restore.")
            sys.exit(1)
        restore_incrementals(args.backup_dir, args.dest)
    else:
        logger.info("Initiating backup operation")
        mount_points = get_mount_points()
        dest = ask_user_path(mount_points, args.silent)
        create_backup(dest, args.incremental, args.silent, args.fast)
        safe_unmount(dest)
        logger.info("Main execution completed")