set -u
sz() { sudo -n du -sxB1 "$1" 2>/dev/null | cut -f1; }
echo "df before:"; df -B1 / | tail -1
echo -e "BYTES\tITEM\tHOW"
rmitem() { # $1 path $2 owner-mode(user|root)
  [ -e "$1" ] || { echo -e "-\t$1\tMISSING"; return; }
  b=$(sz "$1")
  if [ "$2" = root ]; then sudo -n trash-put "$1" && echo -e "$b\t$1\ttrash-put(root); emptied below"
  else trash-put "$1" && echo -e "$b\t$1\ttrash-put; emptied below"; fi
}
for p in /home/kesha/.npm/_cacache /home/kesha/.cache/pip /home/kesha/.cache/ms-playwright/chromium_headless_shell-1194 \
         /home/kesha/.local/state/orchestra/knowledge-v1 /home/kesha/research-archive/golos-v2-analysis; do rmitem "$p" user; done
for p in /root/.npm/_cacache /root/.cache/pip /root/.cache/uv /root/.cache/ms-playwright /var/cache/orchestra-uv; do rmitem "$p" root; done
echo "trash sizes before empty:"; echo "kesha $(sz /home/kesha/.local/share/Trash)"; echo "root $(sz /root/.local/share/Trash)"
trash-empty -f && echo "kesha trash emptied"
sudo -n -H trash-empty -f && echo "root trash emptied"
echo "kesha trash after: $(sz /home/kesha/.local/share/Trash)  root after: $(sz /root/.local/share/Trash)"
echo "== uv cache prune"; timeout 120 ~/.local/bin/uv cache prune 2>&1 | tail -3
echo "== journal"; sudo -n journalctl --vacuum-size=500M 2>&1 | tail -2; sudo -n journalctl --disk-usage
echo "df after:"; df -B1 / | tail -1
