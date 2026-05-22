#!/bin/sh
echo 'ACTION=="add", KERNEL=="sda1", SUBSYSTEM=="block", RUN+="/var/LxC/vpnui-usb-hotplug.sh"' >/etc/udev/rules.d/99-vpnui.rules

echo '#!/bin/sh' >/var/LxC/vpnui-usb-hotplug.sh
echo '(' >>/var/LxC/vpnui-usb-hotplug.sh
echo '  sleep 8' >>/var/LxC/vpnui-usb-hotplug.sh
echo '  /var/LxC/vpnui-watchdog.sh once' >>/var/LxC/vpnui-usb-hotplug.sh
echo '  /var/LxC/vpnui-watchdog.sh start' >>/var/LxC/vpnui-usb-hotplug.sh
echo ') >/var/LxC/vpnui-usb-hotplug.log 2>&1 &' >>/var/LxC/vpnui-usb-hotplug.sh
chmod +x /var/LxC/vpnui-usb-hotplug.sh

/var/LxC/vpnui-watchdog.sh start
