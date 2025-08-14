import argparse
from pathlib import Path

def parse_args():
    parser = argparse.ArgumentParser(description="Create full or incremental backups, or restore incremental ones.")
    parser.add_argument("-i", "--incremental", action="store_true", help="Perform an incremental backup")
    parser.add_argument("-r", "--restore", action="store_true", help="Restore from incremental backups")
    parser.add_argument("--backup-dir", type=str, help="Directory containing incremental backups")
    parser.add_argument("--dest", type=str, help="Directory to restore into")
    parser.add_argument("-s", "--silent", action="store_true", help="Disabling non-critical performance and progress indicators")

    return parser.parse_args()

def parse_restore():
    parser = argparse.ArgumentParser(description="Restore incremental backups.")
    parser.add_argument("--backup-dir", type=Path, required=True, help="Directory containing incremental backups")
    parser.add_argument("--dest", type=Path, required=True, help="Directory to restore into")

    return parser.parse_args()

if __name__ == "__main__":
    parse_args()
