import os
import tarfile
import subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.progress import Progress, BarColumn, TextColumn, ProgressColumn
from rich.text import Text
import sys

HOME_DIR = Path.home()
SCRIPT_DIR = Path(__file__).resolve().parent
IGNORE_FILE = SCRIPT_DIR / ".backupignore"

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


def collect_files_for_backup(ignore_set, max_workers=8):
    """Parallel collection of a list of files for backup, taking into account .backupignore"""
    all_files = []

    def walk_dir(start_path):
        result = []
        for root, dirs, files in os.walk(start_path):
            root_path = Path(root)
            if should_ignore(root_path, ignore_set):
                dirs[:] = []  # не йти далі
                continue
            for name in files:
                full_path = root_path / name
                if not should_ignore(full_path, ignore_set):
                    rel = os.path.relpath(full_path, HOME_DIR)
                    result.append((str(full_path), rel))
        return result

    for item in HOME_DIR.iterdir():
        if item.is_file() and not should_ignore(item, ignore_set):
            rel = os.path.relpath(item, HOME_DIR)
            all_files.append((str(item), rel))

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


def create_backup(dest_dir):
    now = datetime.now()
    archive_name = f"home-backup-{Path().cwd().name}-{now.strftime('%Y%m%d_%H%M%S')}.tar.gz"
    archive_path = dest_dir / archive_name
    ignore_set = load_ignore_list()

    print("🔍 Scanning files for backup (with .backupignore)...")
    all_files = collect_files_for_backup(ignore_set)
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

    print(f"\n🔐 Creating archive: {archive_path}\n")

    try:
        with tarfile.open(archive_path, "w:gz") as tar, \
            Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.0f}%",
                FileCounterColumn(),
            ) as progress:

            task = progress.add_task("Backing up...", total=total_files)

            for full_path, rel in all_files:
                try:
                    print(f"Adding: {rel}")
                    tar.add(full_path, arcname=rel)
                except Exception as e:
                    print(f"❗ Failed to add {rel}: {e}")
                progress.advance(task)

    except KeyboardInterrupt:
        print("\n⚠️ Backup interrupted by user (Ctrl+C).")
        if tar:
            tar.close()
        safe_unmount(dest_dir)
        print(f"✅ Partial archive saved: {archive_path}")
        sys.exit(0)
    except Exception as e:
        print(f"❗ Error during backup: {e}")
        if tar:
            tar.close()
        sys.exit(1)

    print("\n✅ Backup complete!")


if __name__ == "__main__":
    print()
    mount_points = get_mount_points()
    dest = ask_user_path(mount_points)
    create_backup(dest)
    safe_unmount(dest)