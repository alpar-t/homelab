#!/bin/sh

# Use -f to point OTMonitor to the config file location
cd /config
exec /opt/otmonitor -f /config/otmonitor.conf
