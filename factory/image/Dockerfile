# Factory image: every tool the agents and CI need, at pinned versions (poc-plan.md, Step 2).
# Built and pushed to GHCR by .github/workflows/factory-image.yml, and rebuilt weekly for security fixes.
# Versions were the newest releases at least two weeks old on 2026-10-24; Dependabot proposes updates.
FROM node:24-trixie-slim

ARG SF_CLI_VERSION=2.155.1
ARG CODE_ANALYZER_VERSION=5.16.0
ARG CLAUDE_CODE_VERSION=2.1.296
ARG SF_MCP_VERSION=0.30.15
ARG LWC_JEST_VERSION=7.9.0
ARG PRETTIER_VERSION=3.9.9
ARG PRETTIER_APEX_VERSION=2.3.0
ARG PLAYWRIGHT_CORE_VERSION=1.64.0
ARG GH_VERSION=2.102.0
ARG GITLEAKS_VERSION=8.30.1

ENV DEBIAN_FRONTEND=noninteractive \
    SF_AUTOUPDATE_DISABLE=true \
    SF_DISABLE_TELEMETRY=true \
    SF_USE_GENERIC_UNIX_KEYCHAIN=true \
    SF_CONTAINER_MODE=true \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    NODE_PATH=/usr/local/lib/node_modules \
    PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
    npm_config_update_notifier=false \
    npm_config_fund=false \
    npm_config_audit=false

# Debian trixie: Python 3.13, OpenJDK 21. Code Analyzer v5 needs Java 11+ and Python 3.10+.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git jq unzip python3 python3-yaml openjdk-21-jre-headless chromium fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && git config --system --add safe.directory '*'

# gh and gitleaks from their GitHub releases, checked against the published checksums.
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    garch="$([ "$arch" = amd64 ] && echo x64 || echo "$arch")"; \
    cd /tmp; \
    curl -fsSLO "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${arch}.tar.gz"; \
    curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_checksums.txt" \
      | grep " gh_${GH_VERSION}_linux_${arch}.tar.gz$" | sha256sum -c -; \
    tar -xzf "gh_${GH_VERSION}_linux_${arch}.tar.gz"; \
    install -m 0755 "gh_${GH_VERSION}_linux_${arch}/bin/gh" /usr/local/bin/gh; \
    curl -fsSLO "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${garch}.tar.gz"; \
    curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_checksums.txt" \
      | grep " gitleaks_${GITLEAKS_VERSION}_linux_${garch}.tar.gz$" | sha256sum -c -; \
    tar -xzf "gitleaks_${GITLEAKS_VERSION}_linux_${garch}.tar.gz" gitleaks; \
    install -m 0755 gitleaks /usr/local/bin/gitleaks; \
    rm -rf /tmp/*

RUN npm install -g \
      "@salesforce/cli@${SF_CLI_VERSION}" \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
      "@salesforce/mcp@${SF_MCP_VERSION}" \
      "@salesforce/sfdx-lwc-jest@${LWC_JEST_VERSION}" \
      "prettier@${PRETTIER_VERSION}" \
      "prettier-plugin-apex@${PRETTIER_APEX_VERSION}" \
      "playwright-core@${PLAYWRIGHT_CORE_VERSION}" \
 && sf plugins install "@salesforce/plugin-code-analyzer@${CODE_ANALYZER_VERSION}" \
 && npm cache clean --force

COPY screenshot.js /usr/local/lib/factory/screenshot.js
RUN printf '#!/bin/sh\nexec node /usr/local/lib/factory/screenshot.js "$@"\n' > /usr/local/bin/factory-screenshot \
 && chmod 0755 /usr/local/bin/factory-screenshot \
 && sf --version && claude --version && gh --version && gitleaks version && java -version && python3 --version

WORKDIR /work
