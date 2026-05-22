#!/bin/sh
PID=/var/tmp/vpnui-watchdog.pid
LOG=/var/LxC/vpnui-watchdog.log

if [ "$1" = "stop" ]; then
  if [ -f "$PID" ]; then
    kill `cat "$PID"` 2>/dev/null
    rm -f "$PID"
  fi
  exit 0
fi

if [ "$1" = "once" ]; then
  ps | grep '/var/tmp/vpnui/bin/busybox-mips httpd' | grep -v grep >/dev/null 2>&1
  if [ "$?" != "0" ]; then
    mkdir -p /var/usbmnt/sda1
    mount | grep '/var/usbmnt/sda1' >/dev/null 2>&1 || mount -t ext2 /dev/sda1 /var/usbmnt/sda1 2>/dev/null
    if [ -x /var/usbmnt/sda1/vpnui/start-ram.sh ]; then
      echo "start vpnui" >>"$LOG"
      /var/usbmnt/sda1/vpnui/start-ram.sh >>"$LOG" 2>&1
    fi
  fi
  exit 0
fi

if [ "$1" = "daemon" ]; then
  echo $$ > "$PID"
  echo "watchdog daemon start" >>"$LOG"
  while true
  do
    ps | grep '/var/tmp/vpnui/bin/busybox-mips httpd' | grep -v grep >/dev/null 2>&1
    if [ "$?" != "0" ]; then
      mkdir -p /var/usbmnt/sda1
      mount | grep '/var/usbmnt/sda1' >/dev/null 2>&1 || mount -t ext2 /dev/sda1 /var/usbmnt/sda1 2>/dev/null
      if [ -x /var/usbmnt/sda1/vpnui/start-ram.sh ]; then
        echo "start vpnui" >>"$LOG"
        /var/usbmnt/sda1/vpnui/start-ram.sh >>"$LOG" 2>&1
      fi
    fi
    if [ -x /var/LxC/tgbot/router-tgbot.sh ]; then
      /var/LxC/tgbot/router-tgbot.sh status 2>/dev/null | grep -q running || /var/LxC/tgbot/router-tgbot.sh start >/dev/null 2>&1
    fi
    sleep 60
  done
fi

if [ -f "$PID" ]; then
  kill -0 `cat "$PID"` 2>/dev/null
  if [ "$?" = "0" ]; then
    exit 0
  fi
fi

/var/LxC/vpnui-watchdog.sh daemon >/dev/null 2>&1 &
exit 0
