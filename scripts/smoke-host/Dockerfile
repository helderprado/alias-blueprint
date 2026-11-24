FROM ubuntu:22.04@sha256:f64b2ffc2f10ab8f8505aa56b2664bd846cbb9df87c7e2532e30f7667021c0e6
ENV container=docker DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    systemd systemd-sysv dbus curl ca-certificates python3 python3-venv git \
    openssl default-jre-headless iproute2 iptables conntrack sudo procps \
    tar gzip hostname mount e2fsprogs kmod && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    systemctl mask systemd-udevd.service systemd-udevd-control.socket \
      systemd-udevd-kernel.socket systemd-udev-trigger.service && \
    mkdir -p /workspace/alias-blueprint
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
