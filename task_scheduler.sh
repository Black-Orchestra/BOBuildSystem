user_site=$(python -m site --user-site)
export PATH="$PATH:${user_site}"

taskiq scheduler bobuild.tasks:scheduler \
 --tasks-pattern "${user_site}/**/bobuild/**/tasks*.py" \
 --fs-discover
