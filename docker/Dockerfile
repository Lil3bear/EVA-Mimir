# ============================================================
# Stage 1: 编译 fastcoll + 预编译 Python wheels
# ============================================================
FROM ubuntu:22.04 AS builder

ARG APT_MIRROR=http://mirrors.aliyun.com/ubuntu/

ENV DEBIAN_FRONTEND=noninteractive

RUN echo "deb ${APT_MIRROR} jammy main restricted universe multiverse" > /etc/apt/sources.list \
    && echo "deb ${APT_MIRROR} jammy-updates main restricted universe multiverse" >> /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    g++ make wget unzip ca-certificates \
    python3 python3-pip python3-dev \
    libboost-all-dev libssl-dev libffi-dev libgmp-dev libmpfr-dev libmpc-dev \
    && rm -rf /var/lib/apt/lists/*

# --- fastcoll ---
COPY docker/fastcoll-src/ /tmp/fastcoll-src/
RUN if [ -f /tmp/fastcoll-src/main.cpp ]; then \
        cd /tmp/fastcoll-src && g++ -O2 -o /tmp/fastcoll *.cpp -lboost_filesystem -lboost_system 2>/dev/null \
        || g++ -O2 -o /tmp/fastcoll *.cpp 2>/dev/null \
        || echo "WARN: fastcoll-src compile failed"; \
    fi \
    && if [ ! -f /tmp/fastcoll ]; then \
        echo '#!/bin/bash' > /tmp/fastcoll \
        && echo 'echo "fastcoll placeholder - replace with real binary"' >> /tmp/fastcoll; \
    fi \
    && chmod +x /tmp/fastcoll

# --- Python wheels（在 builder 里预编译，runtime 阶段直接装）---
COPY docker/requirements-solver.txt /tmp/requirements-solver.txt
RUN pip3 install --no-cache-dir --upgrade setuptools wheel \
    && pip3 wheel --no-cache-dir --wheel-dir /tmp/wheels -r /tmp/requirements-solver.txt

# ============================================================
# Stage 2: 最终运行镜像（目标 < 1GB）
# ============================================================
FROM ubuntu:22.04

ARG APT_MIRROR=http://mirrors.aliyun.com/ubuntu/

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/ctf-agent

# LLM 网关配置（走 *.tsecbench.gw 时由 apply_llm_gateway 把 host 改写为
# <host>.tsecbench.gw，key 由网关透传）。
ENV LLM_BASE_URL=https://tokenhub.tencentmaas.com/v1 \
    LLM_API_KEY=sk-0RpIFAcmhuYIIdLKhePbHUVJ3Xy2Dgzd9ijSU7DqojoTBEog \
    LLM_MODEL=deepseek-v4-flash \
    LLM_GATEWAY=1

# 阿里云 apt 源（arm64 构建时传入 --build-arg APT_MIRROR=http://ports.ubuntu.com/ubuntu-ports/）
RUN rm -f /etc/apt/sources.list.d/ubuntu.sources \
    && echo "deb ${APT_MIRROR} jammy main restricted universe multiverse" > /etc/apt/sources.list \
    && echo "deb ${APT_MIRROR} jammy-updates main restricted universe multiverse" >> /etc/apt/sources.list \
    && echo "deb ${APT_MIRROR} jammy-backports main restricted universe multiverse" >> /etc/apt/sources.list \
    && echo "deb ${APT_MIRROR} jammy-security main restricted universe multiverse" >> /etc/apt/sources.list

# 系统工具（精简版：目标 < 1GB）
# 去掉：SageMath(~1.5G) libboost
# gcc 移到 builder 阶段，Solver 需要编译时用 python3 替代
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    curl wget netcat-traditional git \
    openssh-client sshpass \
    patchelf \
    file binutils gdb \
    gcc g++ make \
    libgmp10 libmpfr6 libmpc3 \
    zip unzip \
    php-cli \
    sqlmap \
    nmap dirb hydra \
    jq \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && rm -rf /usr/share/doc /usr/share/man /usr/share/info /usr/share/lintian

# fastcoll — 从 builder 阶段复制
COPY --from=builder /tmp/fastcoll /usr/local/bin/fastcoll

# Python 依赖 — 从预编译 wheels 安装（不带 python3-dev，节省空间）
COPY --from=builder /tmp/wheels /tmp/wheels
COPY docker/requirements-solver.txt /tmp/requirements-solver.txt
RUN pip3 install --no-cache-dir --no-index --find-links /tmp/wheels -r /tmp/requirements-solver.txt \
    && rm -rf /tmp/wheels /tmp/requirements-solver.txt /root/.cache \
    && find /usr/lib/python3 -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
    find /usr/local/lib/python3* -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
    find /usr/local/lib/python3* -name '*.pyc' -delete 2>/dev/null; \
    true

# 复制代码
COPY solver/ /opt/ctf-agent/solver/
COPY shared/ /opt/ctf-agent/shared/
COPY prompts/ /opt/ctf-agent/prompts/
COPY skills/ /opt/ctf-agent/skills/

# Skills 快捷链接（prompt 里用 /skills/xxx 引用）
RUN ln -sf /opt/ctf-agent/skills /skills

# 目录扫描字典（内置大字典，来自 BreachWeave）
RUN mkdir -p /usr/share/wordlists/dirb \
    && printf '%s\n' \
    admin api backup config css db debug doc download \
    error flag fonts html img include index js login \
    logs manage media panel phpmyadmin private robots.txt \
    secret server-status shell sitemap.xml sql static \
    swagger test tmp upload uploads user wp-admin wp-login.php \
    .env .git .git/HEAD .svn .htaccess .user.ini \
    api/v1 api/v2 console dashboard graphql health info \
    metrics monitor status actuator actuator/env \
    > /usr/share/wordlists/dirb/common.txt
COPY docker/wordlists/ /usr/share/wordlists/

# 工作目录
WORKDIR /root/workspace

# 容器启动命令
CMD ["python3", "/opt/ctf-agent/solver/main.py"]
