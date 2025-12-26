# OTMonitor - OpenTherm Gateway Monitor
# Based on jlesage/baseimage-gui for VNC web access

FROM jlesage/baseimage-gui:ubuntu-20.04

EXPOSE 5800 7686

# Install dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      curl \
      libxss1 \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Download OTMonitor binary
RUN curl -fsSL https://otgw.tclcode.com/download/otmonitor-x64 -o /opt/otmonitor && \
    chmod +x /opt/otmonitor

# Copy the start script
COPY startapp.sh /startapp.sh
RUN chmod +x /startapp.sh

# Set the name of the application
ENV APP_NAME="OTMonitor"

# Create config directory
RUN mkdir -p /config

