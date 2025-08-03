#!/bin/bash

RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR=$(dirname "$(realpath "$0")")

if [ -d "$SCRIPT_DIR/venv" ]; then
    echo "Activating virtual environment..."
    source $SCRIPT_DIR/venv/bin/activate
else
    echo -e "${RED}Virtual environment not found! Please run install.sh first.${NC}"
    exit 1
fi

python3 $SCRIPT_DIR/main.py