set -u
U=$(cat /proc/sys/kernel/random/uuid); S=/tmp/v806-$U; mkdir "$S"
LOG=$HOME/v806-moved.tsv; : > $LOG
echo "df before:"; df -B1 / | tail -1
busy() { # $1 path: open files/cwd, or referenced in any process cmdline
  [ -n "$(sudo -n lsof +D "$1" 2>/dev/null | head -1)" ] && return 0
  [ -n "$(sudo -n lsof "$1" 2>/dev/null | head -1)" ] && return 0
  pgrep -f -- "$1" >/dev/null 2>&1 && return 0
  return 1; }
protect() { # git / sqlite / db inside
  [ -n "$(find "$1" \( -name .git -o -name '*.db' -o -name '*.sqlite*' \) -print -quit 2>/dev/null)" ]; }
move() { b=$(du -sxB1 "$1" 2>/dev/null | cut -f1); printf '%s\t%s\n' "$b" "$1" >> $LOG; mv "$1" "$S/$(echo "$1" | tr / _)"; }
for p in /tmp/* /tmp/.[!.]*; do
  [ -e "$p" ] || continue
  case "$p" in /tmp/v806-*|/tmp/.X11-unix|/tmp/.ICE-unix|/tmp/.font-unix|/tmp/.Test-unix|/tmp/claude-1001|/tmp/systemd-private-*|/tmp/tmux-*|/tmp/snap-private-tmp) continue;; esac
  [ "$(stat -c %U "$p")" = kesha ] || continue
  [ -n "$(find "$p" -mmin -120 -print -quit 2>/dev/null)" ] && { echo "keep fresh: $p"; continue; }
  protect "$p" && { echo "keep git/db: $p"; continue; }
  busy "$p" && { echo "keep busy: $p"; continue; }
  move "$p"
done
for p in /home/kesha/.cache/ms-playwright /home/kesha/.cache/pip /home/kesha/.npm/_cacache; do
  [ -e "$p" ] || continue
  busy "$p" && { echo "keep busy: $p"; continue; }
  move "$p"
done
echo "moved:"; awk -F'\t' '{s+=$1;print $1/1e6" MB\t"$2}END{print s/1e9" GB total"}' $LOG
trash "$S" && trash-rm "v806-$U" && echo trashed-and-removed
df -B1 / | tail -1
ls ~/.local/share/Trash/files 2>/dev/null | grep -c "v806-$U"
