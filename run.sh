#!/usr/bin/env bash
# Araceli launcher for Git Bash (and other POSIX shells): activates the
# project venv and starts the app.

cd "$(dirname "$0")" || exit 1

if [ ! -f ".venv/Scripts/activate" ] && [ ! -f ".venv/bin/activate" ]; then
    echo "Virtual environment not found. Create it with:"
    echo "    python -m venv .venv"
    echo "    .venv/Scripts/pip install -r requirements.txt"
    exit 1
fi

# Windows venvs keep scripts in .venv/Scripts; POSIX venvs use .venv/bin.
if [ -f ".venv/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
else
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

python main.py
