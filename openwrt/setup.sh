#!/bin/sh
# Convenience setup launcher for OpenWrt (runs setup.py inside Ubuntu chroot)
if [ -d "/tmp/noble" ]; then
    exec chroot /tmp/noble python3 /root/setup.py "$@"
else
    echo "Error: /tmp/noble chroot is not mounted or initialized."
    echo "Start the service first: /etc/init.d/spotify_bridge start"
    exit 1
fi
