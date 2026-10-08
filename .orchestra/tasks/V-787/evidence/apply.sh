set -e
sp() { sudo -n systemctl set-property "$@"; echo "ok: $*"; }
sp system.slice MemoryMin=2G MemoryLow=10G
sp kesha-bot-vps.service MemoryMin=1536M MemoryLow=4G CPUWeight=500 IOWeight=500
sp orchestra.service MemoryLow=4G CPUWeight=200 IOWeight=200
sp nginx.service MemoryLow=256M CPUWeight=150 IOWeight=150
sp ssh.service MemoryLow=128M CPUWeight=150 IOWeight=150
sp telegram-bot-api.service MemoryLow=512M CPUWeight=150 IOWeight=150
sp orchestra-proxy.service MemoryLow=128M CPUWeight=150 IOWeight=150
for u in xray hysteria-server mtg tinyproxy; do sp $u.service MemoryLow=128M CPUWeight=150 IOWeight=150; done
