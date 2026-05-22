#!/bin/sh
mkdir -p /var/usbmnt/sda1
mount | grep /var/usbmnt/sda1 >/dev/null 2>&1 || mount -t ext2 /dev/sda1 /var/usbmnt/sda1 2>/dev/null
/var/usbmnt/sda1/vpnui/start-ram.sh
[ -x /var/LxC/install-vpnui-current-session.sh ] && /var/LxC/install-vpnui-current-session.sh
[ -x /var/LxC/vpnui-watchdog.sh ] && /var/LxC/vpnui-watchdog.sh start
[ -x /var/LxC/tgbot/router-tgbot.sh ] && /var/LxC/tgbot/router-tgbot.sh start >/dev/null 2>&1
