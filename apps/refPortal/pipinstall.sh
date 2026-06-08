module=$1

#!/bin/bash

echo "=== Comprehensive Python 3.x Search ==="

# Function to get Python version
get_python_version() {
    local python_exe="$1"
    if [[ -x "$python_exe" ]]; then
        "$python_exe" --version 2>/dev/null | sed 's/Python //'
    fi
}

# Search for all python3* executables
echo "Searching for Python 3.x executables..."

locations="./.venv/bin /usr/bin /usr/local/bin /opt/homebrew/bin ~/.local/bin ~/.pyenv/shims ~/.pyenv/versions/*/bin"

# Search in PATH and common locations
find $locations -name "python3*" -type f -executable 2>/dev/null | while read -r python_exe; do
    echo "Found: $python_exe..."
    version=$(get_python_version "$python_exe")
    if [[ "$version" =~ ^3\.[0-9]+ ]]; then
        echo "Found: $python_exe (Version: $version)"
        $python_exe -m pip install ${module}
    fi
done

# Also check for symlinks
echo "Checking for symlinks..."
find $locations -name "python3*" -type l 2>/dev/null | while read -r symlink; do
    echo "Found symlink: $symlink"
    target=$(readlink -f "$symlink")
    if [[ -x "$target" ]]; then
        version=$(get_python_version "$target")
        if [[ "$version" =~ ^3\.[0-9]+ ]]; then
            echo "Found symlink: $symlink -> $target (Version: $version)"
            $target -m pip install ${module}
        fi
    fi
done

pip install ${module}