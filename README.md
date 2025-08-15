# Backulator

<p align="center">
  <a href="https://ko-fi.com/v1mer" target="_blank">
    <img src="https://img.shields.io/badge/Support-Ko--fi-FF5E5B?style=flat-square&logo=ko-fi&logoColor=white" alt="Support me on Ko-fi" />
  </a>
  <a href="mailto:mpatik2006@gmail.com">
    <img src="https://img.shields.io/badge/Donate-PayPal-00457C?style=flat-square&logo=paypal&logoColor=white" alt="Donate via PayPal" />
  </a>
</p>

Backulator is a Python-based utility designed to create backups of a user's home directory (`/home/user`) to a specified external disk or, if no external disk is detected, to the home directory itself. The program respects a `.backupignore` file to exclude specific files or directories from the backup process. It features a progress bar, parallel file scanning, incremental backups, restore functionality, and safe unmounting of external drives after the backup is complete.

## Features
- **Automatic Detection of External Drives**: Detects mounted external drives (e.g., USB flash drives) using `lsblk`.
- **Customizable Ignore List**: Uses a `.backupignore` file to exclude specified files or directories from the backup, supporting wildcard patterns (e.g., `*.log` or `Downloads/*`).
- **Parallel File Scanning**: Utilizes multi-threading for faster file collection with `ThreadPoolExecutor`.
- **Progress Tracking**: Displays a rich progress bar using the `rich` library, showing the backup progress, file count, and large file progress (for files over 10 MB).
- **Incremental Backups**: Supports incremental backups by tracking file changes using metadata (file hashes and modification times) stored in `backup_metadata.json`, only backing up modified or new files.
- **Restore Functionality**: Allows restoration of files from full and incremental backups, respecting the `.backupignore` file and metadata to ensure the latest file versions are restored.
- **Safe Unmounting**: Automatically unmounts the external drive after the backup or restore is complete or interrupted.
- **Error Handling**: Gracefully handles interruptions (e.g., Ctrl+C) and errors, ensuring partial backups are saved and drives are safely unmounted.

## Prerequisites
- Python 3.6 or higher
- Required Python packages (listed in `requirements.txt`):
  - `rich` for progress bar visualization
- Linux system with `lsblk` and `umount` commands available
- A virtual environment (recommended, set up via `install.sh`)

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/HappyMaxxx/backulator.git
   cd backulator
   ```

2. Run the `install.sh` script to set up the virtual environment and install dependencies:
   ```bash
   ./install.sh
   ```
   - This script creates a virtual environment in the `venv` directory and installs the required Python packages listed in `requirements.txt`.
   - Ensure the script is executable before running:
     ```bash
     chmod +x install.sh
     ```

3. Ensure the `run.sh` script is executable:
   ```bash
   chmod +x run.sh
   ```

## Usage
1. Create or edit the `.backupignore` file in the project directory to specify files or directories to exclude from the backup. For example:
   ```
   .steam/
   .cache/
   Downloads/arduino-1.8.19/
   *.log
   temp/*
   ```

2. Run the backup script:
   ```bash
   ./run.sh
   ```

3. Follow the prompts:
   - If external drives are detected, select one by entering its number.
   - If no drive is selected or found, the backup will be saved to the home directory.
   - Confirm the backup operation after reviewing the list of files to be backed up.

4. The backup will be created as a `.tar.gz` archive with a timestamped name (e.g., `home-backup-<project_dir>-full-YYYYMMDD_HHMMSS.tar.gz` for full backups or `home-backup-<project_dir>-incremental-YYYYMMDD_HHMMSS.tar.gz` for incremental backups).

5. To perform an incremental backup, run:
   ```bash
   ./run.sh --incremental
   ```

6. To restore from backups:
   ```bash
   ./run.sh --restore --backup-dir /path/to/backup/dir --dest /path/to/restore/dir
   ```
   - The restore process will process all `.tar.gz` backup files in the specified backup directory, applying full and incremental backups in chronological order, respecting the `.backupignore` file and metadata to restore the latest versions of files.

7. To run the backup in silent mode (suppressing interactive prompts and progress output):
   ```bash
   ./run.sh --silent
   ```
   The --silence option disables interactive prompts (e.g., drive selection or confirmation) and progress bars, making it suitable for automated scripts or background tasks. In this mode, the backup is saved to the default location (home directory if no external drive is detected) without user input.

   > **Important**: In this mode, the first available flash drive is selected, or if no flash drives are found, it saves to the home directory.

## Incremental Backups
- **How It Works**: Incremental backups only include files that have changed since the last backup (full or incremental). The program tracks changes using file modification times and SHA-256 hashes stored in `backup_metadata.json`.
- **Metadata**: The `backup_metadata.json` file stores file paths, modification times, hashes, and status (e.g., "present" or "deleted") to determine which files need to be backed up or marked as deleted.
- **Deleted Files**: Files that no longer exist in the source directory but were present in previous backups are marked as "deleted" in the metadata during incremental backups.
- **Performance**: Incremental backups are faster than full backups as they only process changed or new files.

## Restore Functionality
- **Process**: The restore functionality processes all backup archives (full and incremental) in the specified backup directory, sorted by timestamp. It restores the latest version of each file, skipping ignored files and respecting the metadata status (e.g., skipping files marked as "deleted").
- **Progress Tracking**: A progress bar displays the number of files restored and the overall progress.
- **Error Handling**: If a file cannot be restored (e.g., due to permissions), an error message is displayed, and the process continues with the next file.
- **Destination**: Files are restored to the specified destination directory, with parent directories created as needed.

## .backupignore File
The `.backupignore` file allows you to specify files or directories to exclude from backups and restores. It supports:
- **Exact Paths**: Specific files or directories (e.g., `.steam/`, `Downloads/arduino-1.8.19/`).
- **Wildcard Patterns**: Patterns using `*` (matches any characters) and `?` (matches a single character). For example:
  - `*.log` excludes all files with the `.log` extension.
  - `temp/*` excludes all files and subdirectories in the `temp` directory.
- **Comments**: Lines starting with `#` are ignored, allowing for comments.
- **Example**:
  ```
  .steam/
  .cache/
  .local/share/Trash/
  Downloads/arduino-1.8.19/
  *.log
  temp/*
  # Exclude all temporary files
  *.tmp
  ```

## File Structure
- `main.py`: The main backup script, handling both full and incremental backups and initiating restores.
- `restore_incremental.py`: Script for restoring files from full and incremental backups.
- `.backupignore`: File specifying paths and patterns to exclude from backups and restores.
- `backup_metadata.json`: Stores metadata for incremental backups (file paths, modification times, hashes, and status).
- `run.sh`: Shell script to activate the virtual environment and run the backup.
- `install.sh`: Shell script to set up the virtual environment and install dependencies.
- `requirements.txt`: Lists required Python packages.

## Running the Backup
Before running the backup, ensure the virtual environment is set up by executing `install.sh` (see **Installation** section). The `run.sh` script then activates the virtual environment and runs `main.py`. Example:
```bash
./install.sh
./run.sh
```

## Notes
- The backup process uses the `tarfile` module to create a compressed `.tar.gz` archive.
- The program scans the home directory in parallel to improve performance, with a default of 10 worker threads for incremental backups and 8 for full backups.
- Estimated backup time is calculated based on the number of files (approximately 0.02 seconds per file, with a minimum of 3 seconds).
- The program supports graceful interruption (Ctrl+C), saving any partial backup and safely unmounting the destination drive.
- Large files (over 10 MB) have individual progress bars during backup to provide detailed progress tracking.
- The restore process ensures that only the latest version of each file is restored, based on modification times and metadata.

## 🙌 Support the Project

If you find this project useful and would like to support its development, consider donating:

- 💖 Ko-fi: [https://ko-fi.com/v1mer](https://ko-fi.com/v1mer)
- 📬 PayPal: mpatik2006@gmail.com

Your support helps me dedicate more time to improving this project. Thank you! 🙏

## Contributing
Contributions are welcome! Please submit a pull request or open an issue on GitHub.

## License
This project is licensed under the MIT License. See the `LICENSE` file for details.