# Rollback V-787: removes only the values set by V-787; orchestra.service MemoryHigh/Max untouched.
set -e
sudo -n systemctl set-property system.slice MemoryMin= MemoryLow=
sudo -n systemctl set-property kesha-bot-vps.service MemoryMin= MemoryLow= CPUWeight= IOWeight=
sudo -n systemctl set-property orchestra.service MemoryLow= CPUWeight= IOWeight=
for u in nginx ssh telegram-bot-api orchestra-proxy xray hysteria-server mtg tinyproxy; do sudo -n systemctl set-property $u.service MemoryLow= CPUWeight= IOWeight=; done
