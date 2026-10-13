set -u
df -B1 / | tail -1
for p in /root/.npm/_cacache /root/.cache/pip /root/.cache/uv /root/.cache/ms-playwright; do
  b=$(sudo -n du -sxB1 $p | cut -f1); sudo -n trash-put "$p" && echo -e "$b\t$p\ttrash-put(root)"; done
sudo -n -H trash-empty -f && echo "root trash emptied: $(sudo -n du -sxB1 /root/.local/share/Trash | cut -f1)"
echo "leftover kesha trash:"; sudo -n du -sxB1 /home/kesha/.local/share/Trash/files/* | awk '{print $1, $2}'
sudo -n env XDG_DATA_HOME=/home/kesha/.local/share trash-empty -f 2>&1 | tail -2
echo "kesha trash after: $(sudo -n du -sxB1 /home/kesha/.local/share/Trash | cut -f1)"; ls /home/kesha/.local/share/Trash/files | head
df -B1 / | tail -1
