#!/bin/bash

# Define ANSI color codes for user feedback
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No color

# Resolve the script's directory (handles symbolic links)
SCRIPT_DIR=$(dirname "$(realpath "$0")") || {
    echo -e "${RED}Error: Failed to determine script directory${NC}"
    exit 1
}

# Check if python3 is installed
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: python3 is not installed. Please install Python 3.6 or higher.${NC}"
    exit 1
fi

# Check if main.py exists
if [ ! -f "$SCRIPT_DIR/main.py" ]; then
    echo -e "${RED}Error: main.py not found in $SCRIPT_DIR${NC}"
    exit 1
fi

# Check if virtual environment exists
if [ -d "$SCRIPT_DIR/venv" ] && [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    echo "Activating virtual environment at $SCRIPT_DIR/venv..."
    source "$SCRIPT_DIR/venv/bin/activate" || {
        echo -e "${RED}Error: Failed to activate virtual environment${NC}"
        exit 1
    }
else
    echo -e "${RED}Error: Virtual environment not found at $SCRIPT_DIR/venv. Please run install.sh first.${NC}"
    exit 1
fi

# Run the main Backulator script with any provided arguments
echo -e "${GREEN}Running Backulator backup script...${NC}"
python3 "$SCRIPT_DIR/main.py" "$@" || {
    echo -e "${RED}Error: Backulator script failed with exit code $?${NC}"
    deactivate 2>/dev/null # Deactivate virtual environment if active
    exit 1
}

# Inform user of success and how to deactivate
echo -e "${GREEN}Backulator script completed successfully!${NC}"
echo "The virtual environment is still active. To deactivate, run: deactivate"