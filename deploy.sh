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
    python3 -m venv "$APP_DIR/venv"
fi
# shellcheck disable=SC1091
source "$APP_DIR/venv/bin/activate"
python -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
if [ "$SKIP_DEPS" -eq 0 ]; then
    echo ">>> 安装 Python 依赖（含 torch，约 2GB，首次会比较久）..."
    pip install -q -r "$APP_DIR/requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
fi

# ---------------------------------------------------------------- 模型预热
echo ">>> 检查模型文件..."
if ! python -m app.tools.prefetch_models --check; then
    echo "    模型尚未下载，开始拉取（向量模型约 100MB，重排模型约 1GB）..."
    python -m app.tools.prefetch_models || echo "    !! 下载未完成，服务仍可运行（对应能力会自动跳过）"
fi

# ---------------------------------------------------------------- systemd
echo ">>> 注册 systemd 服务..."
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
