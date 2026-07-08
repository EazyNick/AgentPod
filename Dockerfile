# AgentPod agent container (BUILD-GUIDE §4.1, Phase 1 slim variant).
FROM ubuntu:24.04

# LAYER 1 (rarely changes): base deps, locales, tzdata,
#   Python + network tools (so agents can write/run test scripts: ping/DHCP/SSID etc.)
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git openssh-client ca-certificates unzip locales tzdata \
        python3 python3-pip python3-venv \
        iputils-ping iproute2 dnsutils \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*
ENV LANG=en_US.UTF-8 LANGUAGE=en_US:en LC_ALL=en_US.UTF-8

# LAYER 2 (occasionally): Node.js (for claude CLI + npx-based MCP later)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# LAYER 2b (occasionally): DUT network test tooling for agent scripts
#   ping/scan/throughput/capture + DHCP + best-effort wireless + Python net libs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        nmap iperf3 arp-scan tcpdump traceroute mtr-tiny netcat-openbsd \
        isc-dhcp-client iw wireless-tools wpasupplicant rfkill wget \
        python3-scapy python3-requests \
    && rm -rf /var/lib/apt/lists/*

# LAYER 2c (occasionally): Playwright + Chromium for the browser MCP (DUT web UI).
#   Browser lives in a shared, world-readable path so the non-root agent can use it.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN npx -y playwright@latest install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*

# LAYER 3 (occasionally): non-root agent user (uid 1000) + home
RUN (userdel -r ubuntu 2>/dev/null || true) \
    && useradd -m -u 1000 -s /bin/bash agent \
    && mkdir -p /home/agent/.claude /home/agent/context /project \
    && chown -R agent:agent /home/agent /project

# LAYER 4 (occasionally): claude CLI installed globally
RUN npm install -g @anthropic-ai/claude-code

# LAYER 5 (frequently): entrypoint + skills installer
#   Strip any CR (Windows checkouts can introduce CRLF; a CRLF shebang breaks exec).
COPY docker/agent-entrypoint.sh /usr/local/bin/agent-entrypoint.sh
COPY docker/agent-skills.py /usr/local/bin/agent-skills.py
RUN sed -i 's/\r$//' /usr/local/bin/agent-entrypoint.sh /usr/local/bin/agent-skills.py \
    && chmod +x /usr/local/bin/agent-entrypoint.sh /usr/local/bin/agent-skills.py

USER agent
WORKDIR /project
ENTRYPOINT ["/usr/local/bin/agent-entrypoint.sh"]
CMD ["sleep", "infinity"]
