FROM ubuntu:24.04
ARG SYSTEMD_VERSION=255.4-1ubuntu8.18
ENV DEBIAN_FRONTEND=noninteractive container=docker
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod 755 /usr/sbin/policy-rc.d \
 && apt-get update \
 && apt-get install -y --no-install-recommends systemd=${SYSTEMD_VERSION} systemd-sysv=${SYSTEMD_VERSION} dbus python3 passwd \
 && test "$(dpkg-query -W -f='${Version}' systemd)" = "${SYSTEMD_VERSION}" \
 && userdel ubuntu && useradd --uid 1000 --create-home fixture \
 && mkdir -p /opt/provenance-proof /var/lib/provenance-proof \
 && chown fixture:fixture /var/lib/provenance-proof \
 && rm -rf /var/lib/apt/lists/*
COPY probe.py /opt/provenance-proof/probe.py
COPY provenance-proof.service provenance-proof.timer /etc/systemd/system/
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
