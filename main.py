import os
import tarfile
from pathlib import Path
import subprocess
from datetime import datetime

HOME_DIR = Path.home()
SCRIPT_DIR = Path(__file__).resolve().parent
IGNORE_FILE = SCRIPT_DIR / ".backupignore"


def get_mount_points():
    """
    Returns a list of mount points for removable devices (USB, flash drives, etc.).
    Checks several standard mount locations: /media, /run/media, /mnt
    """
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


def create_backup(dest_dir):
    now = datetime.now()
    archive_name = f"home-backup-{Path().cwd().name}-{now.strftime('%Y%m%d_%H%M%S')}.tar.gz"
    archive_path = dest_dir / archive_name
    ignore_set = load_ignore_list()

    print(f"Creating an archive {archive_path}...")

    with tarfile.open(archive_path, "w:gz") as tar:
        for root, dirs, files in os.walk(HOME_DIR):
            for name in files + dirs:
                full_path = os.path.join(root, name)
                if not should_ignore(full_path, ignore_set):
                    try:
                        print(os.path.relpath(full_path, HOME_DIR))
                        tar.add(full_path, arcname=os.path.relpath(full_path, HOME_DIR))
                    except Exception as e:
                        print(f"❗ Failed to add {full_path}: {e}")
    print("✅ Done!")


if __name__ == "__main__":
    mount_points = get_mount_points()
    dest = ask_user_path(mount_points)
    create_backup(dest)
