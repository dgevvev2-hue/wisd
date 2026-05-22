#!/bin/sh
echo "nameserver 94.140.14.14" >/etc/resolv.conf
echo "nameserver 94.140.15.15" >>/etc/resolv.conf
echo "nameserver 9.9.9.9" >>/etc/resolv.conf
echo "nameserver 149.112.112.112" >>/etc/resolv.conf

iptables -t nat -C PREROUTING -i br2 -p udp --dport 53 -j REDIRECT --to-ports 53 2>/dev/null || \
  iptables -t nat -I PREROUTING 1 -i br2 -p udp --dport 53 -j REDIRECT --to-ports 53
iptables -t nat -C PREROUTING -i br2 -p tcp --dport 53 -j REDIRECT --to-ports 53 2>/dev/null || \
  iptables -t nat -I PREROUTING 1 -i br2 -p tcp --dport 53 -j REDIRECT --to-ports 53
iptables -C FORWARD -i br2 -p tcp --dport 853 -j REJECT 2>/dev/null || \
  iptables -I FORWARD 1 -i br2 -p tcp --dport 853 -j REJECT
