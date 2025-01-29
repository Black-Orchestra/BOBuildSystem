#!/usr/bin/env bash

# Doing this here again dynamically just to be safe.
# This is also hard-coded in the Dockerfile.
user_site=$(python -m site --user-site)
echo "user_site=${user_site}"
export PATH="$PATH:${user_site}"

module_path=$(python -c "from pathlib import Path; import bobuild; print(Path(bobuild.__file__).parent)")
echo "module_path=${module_path}"
cd "${module_path}" || exit

taskiq scheduler bobuild.tasks:scheduler \
 --tasks-pattern "**/tasks*.py" \
 --fs-discover
