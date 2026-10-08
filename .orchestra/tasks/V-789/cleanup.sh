set -u
U=$(cat /proc/sys/kernel/random/uuid); S=/tmp/v789-$U
mkdir "$S"
echo "df before:"; df -B1 / | tail -1
n=0; bytes=0
for d in /tmp/pytest-of-kesha/*/; do
  d=${d%/}
  [ -n "$(find "$d" -mmin -60 -print -quit)" ] && { echo "keep (fresh): $d"; continue; }
  if lsof +D "$d" >/dev/null 2>&1 || [ -n "$(sudo -n lsof +D "$d" 2>/dev/null | head -1)" ]; then echo "keep (open): $d"; continue; fi
  b=$(du -sB1 "$d" | cut -f1); bytes=$((bytes+b)); n=$((n+1))
  mv "$d" "$S/"
done
echo "moved $n dirs, $bytes bytes into $S"
trash "$S" && trash-rm "v789-$U" && echo trashed-and-removed
df -B1 / | tail -1
ls /tmp/pytest-of-kesha | wc -l
ls ~/.local/share/Trash/files | grep -c "v789-$U"
