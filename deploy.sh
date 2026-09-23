#!/bin/bash
# ============================================================================
# agri-kb 一键部署（Ubuntu / Debian，需要 root）
#
#   sudo bash deploy.sh              # 首次部署或更新
#   sudo bash deploy.sh --no-deps    # 跳过依赖安装，只更新服务配置
#
# 脚本是幂等的：重复执行只更新依赖与服务配置，不会删除数据。
# ============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_USER="${APP_USER:-root}"
PORT="${PORT:-8001}"
PYTHON="${PYTHON:-python3}"
# 默认不指定索引：云服务器通常已在 /etc/pip.conf 配好内网镜像
# （如阿里云 ECS 的 mirrors.cloud.aliyuncs.com，免流量费且更快）。
# 显式传 -i 会覆盖系统配置，反而可能连不上——所以默认留空。
# 需要指定时：sudo PIP_INDEX=http://你的源/simple bash deploy.sh
PIP_INDEX="${PIP_INDEX:-}"
SKIP_DEPS=0

for arg in "$@"; do
    case "$arg" in
        --no-deps) SKIP_DEPS=1 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "请用 root 运行：sudo bash deploy.sh"
    exit 1
fi

echo ">>> 应用目录：$APP_DIR"
echo ">>> 监听端口：$PORT"

# ---------------------------------------------------------------- Python 版本
# 必须先查这个：Python 3.6 上 pip 会报 "from versions: none"，
# 因为新版 fastapi 全部要求 Python >= 3.7，版本会被静默过滤掉。
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "!!! 找不到 $PYTHON，请先安装 Python 3.8+"
    exit 1
fi
PY_VER="$("$PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
PY_OK="$("$PYTHON" -c 'import sys; print(1 if sys.version_info >= (3, 8) else 0)')"
PY_GOOD="$("$PYTHON" -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')"
echo ">>> Python 版本：$PY_VER ($PYTHON)"
if [ "$PY_OK" -ne 1 ]; then
    cat <<EOF
!!! Python 版本过低：$PY_VER，本项目需要 3.8 及以上。

    Ubuntu 18.04 自带 Python 3.6，直接装依赖会报
    "Could not find a version that satisfies the requirement ... (from versions: none)"。

    解决办法（二选一）：

    A. 装一个新版 Python 并用它执行本脚本：
         apt-get install -y software-properties-common
         add-apt-repository -y ppa:deadsnakes/ppa
         apt-get update
         apt-get install -y python3.11 python3.11-venv
         rm -rf venv
         PYTHON=python3.11 bash deploy.sh

    B. 换成 Ubuntu 22.04 / 24.04，自带 Python 3.10 / 3.12。

    另外注意：venv 已经建过就不能复用，上面的 A 方案里带了 rm -rf venv。
EOF
    exit 1
fi
if [ "$PY_GOOD" -ne 1 ]; then
    echo "    ! 提示：$PY_VER 可以运行，但 torch / numpy 等会解析到较旧版本，建议 3.10 及以上"
fi

# ---------------------------------------------------------------- 依赖
if [ "$SKIP_DEPS" -eq 0 ]; then
    echo ">>> 安装系统依赖..."
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip nginx curl
fi

if [ ! -f "$APP_DIR/.env" ]; then
    echo "!!! 缺少 $APP_DIR/.env"
    echo "    先执行：cp .env.example .env && vi .env   填入 LLM_API_KEY"
    exit 1
fi
chmod 600 "$APP_DIR/.env"

# ---------------------------------------------------------------- Python 环境
echo ">>> 准备虚拟环境..."
if [ ! -d "$APP_DIR/venv" ]; then
    "$PYTHON" -m venv "$APP_DIR/venv"
fi
# shellcheck disable=SC1091
source "$APP_DIR/venv/bin/activate"

if [ "$SKIP_DEPS" -eq 0 ]; then
    echo ">>> 当前 pip 索引配置："
    pip config list 2>/dev/null | sed 's/^/    /' || true
    [ -z "$(pip config list 2>/dev/null)" ] && echo "    (无自定义配置，使用官方 PyPI)"

    echo ">>> 安装 Python 依赖（含 torch，约 2GB，首次会比较久）..."
    pip install --upgrade pip -q || true

    # 候选顺序：显式指定 > 系统配置 > 清华 > 官方
    candidates=()
    [ -n "$PIP_INDEX" ] && candidates+=("$PIP_INDEX")
    candidates+=("")
    candidates+=("https://pypi.tuna.tsinghua.edu.cn/simple")
    candidates+=("https://pypi.org/simple")

    install_ok=0
    for src in "${candidates[@]}"; do
        label="${src:-系统 pip 配置}"
        echo ">>> 尝试源：$label"
        if [ -n "$src" ]; then
            pip install -r "$APP_DIR/requirements.txt" -i "$src" && install_ok=1 && break
        else
            pip install -r "$APP_DIR/requirements.txt" && install_ok=1 && break
        fi
        echo "    ! 该源失败，换下一个"
    done

    if [ "$install_ok" -ne 1 ]; then
        cat <<'EOF'
!!! 依赖安装失败，请依次排查：

    1. 看系统配置的索引是否可用（云服务器一般是内网源）：
         pip config list
         cat /etc/pip.conf

    2. 直接测这个源能不能通（HEAD 请求常被镜像站拒绝，要用 GET）：
         curl -s -o /dev/null -w "%{http_code}\n" http://mirrors.cloud.aliyuncs.com/pypi/simple/fastapi/

    3. 需要换源时显式指定（会覆盖系统配置）：
         sudo PIP_INDEX=https://pypi.org/simple bash deploy.sh

    4. 若报 "from versions: none"，且 Python 是 3.7 及以下，看脚本开头的提示。
EOF
        exit 1
    fi
fi

# ---------------------------------------------------------------- 模型预热
echo ">>> 检查模型文件..."
if ! python -m app.tools.prefetch_models --check; then
    echo "    模型尚未下载，开始拉取（向量模型约 100MB，重排模型约 1GB）..."
    python -m app.tools.prefetch_models || echo "    !! 下载未完成，服务仍可运行（对应能力会自动跳过）"
fi

# ---------------------------------------------------------------- systemd
echo ">>> 启动前自检..."
# 关键：必须在动 systemd 之前确认新版本真的能跑起来。
# 否则 --no-deps 之类的误用会把正在工作的旧服务停掉，变成一次事故。
if [ ! -x "$APP_DIR/venv/bin/uvicorn" ]; then
    cat <<EOF
!!! $APP_DIR/venv/bin/uvicorn 不存在，说明依赖没装全。

    现有服务未被改动，仍在正常运行。

    先补装依赖再执行本脚本（--no-deps 只应在依赖装好之后使用）：
        source $APP_DIR/venv/bin/activate
        pip install -r $APP_DIR/requirements.txt
        deactivate
        sudo bash deploy.sh --no-deps
EOF
    exit 1
fi
if ! "$APP_DIR/venv/bin/python" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    echo "!!! venv 里缺少 fastapi / uvicorn，依赖安装不完整。"
    echo "    现有服务未被改动。请先 pip install -r requirements.txt"
    exit 1
fi
"$APP_DIR/venv/bin/python" - <<'PY' || { echo "!!! 应用无法导入，现有服务未被改动。"; exit 1; }
import sys
sys.path.insert(0, ".")
try:
    import main  # noqa: F401
except Exception as exc:
    print("    导入失败：%s" % exc)
    raise SystemExit(1)
PY
echo "    自检通过"

echo ">>> 注册 systemd 服务..."
# 覆盖前先备份，出问题能对着看
if [ -f /etc/systemd/system/agri-kb.service ]; then
    cp /etc/systemd/system/agri-kb.service \
       "/etc/systemd/system/agri-kb.service.bak.$(date +%Y%m%d%H%M%S)"
fi
cat > /etc/systemd/system/agri-kb.service << SVC
[Unit]
Description=agri-kb 农业知识库 RAG 问答服务
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
# 只跑单进程：检索索引与会话都在进程内存里，多 worker 会各自持有一份
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=3
# 优雅退出：等正在生成的回答收尾
TimeoutStopSec=20
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVC

# ---------------------------------------------------------------- nginx
echo ">>> 配置 nginx..."
# 同名 server_name 会被 nginx 直接忽略，提前提醒
CONFLICTS="$(grep -rl 'server_name _;' /etc/nginx/sites-enabled/ 2>/dev/null | grep -v 'agri-kb' || true)"
if [ -n "$CONFLICTS" ]; then
    echo "    ! 下列站点也占用了 server_name _，nginx 只会生效其中一个："
    echo "$CONFLICTS" | sed 's/^/        /'
    echo "      建议把本项目的 server_name 改成你的域名，或先停用旧站点。"
fi
if [ -f /etc/nginx/sites-available/agri-kb ]; then
    cp /etc/nginx/sites-available/agri-kb \
       "/etc/nginx/sites-available/agri-kb.bak.$(date +%Y%m%d%H%M%S)"
fi
cat > /etc/nginx/sites-available/agri-kb << 'NGX'
server {
    listen 80;
    server_name _;

    # 上传文档用，需不小于 .env 里的 MAX_UPLOAD_MB
    client_max_body_size 32m;

    location / {
        proxy_pass http://127.0.0.1:__PORT__;

        # 流式输出（SSE）必须的三项：HTTP/1.1 + 关闭缓冲 + 长超时
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:__PORT__/health;
        access_log off;
    }
}
NGX
sed -i "s/__PORT__/$PORT/g" /etc/nginx/sites-available/agri-kb

ln -sf /etc/nginx/sites-available/agri-kb /etc/nginx/sites-enabled/agri-kb
rm -f /etc/nginx/sites-enabled/default

echo ">>> 启动服务..."
systemctl daemon-reload
systemctl enable agri-kb >/dev/null 2>&1
systemctl restart agri-kb
nginx -t -q && systemctl reload nginx

sleep 3
if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null; then
    echo ">>> 部署成功"
    curl -s "http://127.0.0.1:$PORT/health"; echo
    echo "    查看日志：journalctl -u agri-kb -f"
    echo "    配置 HTTPS：apt install -y certbot python3-certbot-nginx && certbot --nginx -d 你的域名"
else
    echo ">>> 服务未通过健康检查，最近日志："
    journalctl -u agri-kb -n 40 --no-pager
    exit 1
fi
