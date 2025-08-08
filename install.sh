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

# Check Python version (requires 3.6 or higher per README)
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 6 ]; }; then
    echo -e "${RED}Error: Python 3.6 or higher is required. Found Python $PYTHON_VERSION${NC}"
    exit 1
fi

# Check if requirements.txt exists
if [ ! -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo -e "${RED}Error: requirements.txt not found in $SCRIPT_DIR${NC}"
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ -d "$SCRIPT_DIR/venv" ] && [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    echo -e "${GREEN}Virtual environment already exists at $SCRIPT_DIR/venv, skipping creation...${NC}"
else
    echo -e "${GREEN}Creating virtual environment at $SCRIPT_DIR/venv...${NC}"
    python3 -m venv "$SCRIPT_DIR/venv" || {
        echo -e "${RED}Error: Failed to create virtual environment${NC}"
        exit 1
    }
fi

# Activate virtual environment
echo -e "${GREEN}Activating virtual environment...${NC}"
source "$SCRIPT_DIR/venv/bin/activate" || {
    echo -e "${RED}Error: Failed to activate virtual environment${NC}"
    exit 1
}

# Check if pip is available in the virtual environment
if ! command -v pip &>/dev/null; then
    echo -e "${RED}Error: pip not found in virtual environment${NC}"
    exit 1
fi

# Install dependencies
echo -e "${GREEN}Installing dependencies from $SCRIPT_DIR/requirements.txt...${NC}"
pip install -r "$SCRIPT_DIR/requirements.txt" || {
    echo -e "${RED}Error: Failed to install dependencies${NC}"
    deactivate 2>/dev/null # Deactivate virtual environment if active
    exit 1
}

# Success message with next steps
echo -e "${GREEN}Installation complete! The virtual environment is active.${NC}"
echo "To run the backup, execute: ./run.sh"
echo "To deactivate the virtual environment, run: deactivate"