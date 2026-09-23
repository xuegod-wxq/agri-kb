# 部署手册

面向一台全新的 Ubuntu / Debian 云服务器，全程约 15 分钟（不含依赖下载）。

## 0. 服务器要求

| 项目 | 最低 | 建议 |
|---|---|---|
| CPU | 2 核 | 2 核 |
| 内存 | 2 GB | 4 GB（torch + 重排模型约占用 2GB） |
| 磁盘 | 8 GB | 20 GB（依赖约 2GB + 模型约 1.2GB） |
| 系统 | Ubuntu 20.04 | Ubuntu 22.04 / 24.04 |

本项目是 CPU 推理 + 调用云端大模型，**不需要 GPU**。

## 1. 一键部署

```bash
# 拉代码
sudo mkdir -p /opt && cd /opt
sudo git clone <你的仓库地址> agri-kb-v4
cd agri-kb-v4

# 配置密钥（必做，脚本会检查这个文件）
sudo cp .env.example .env
sudo vi .env                 # 填 DEEPSEEK_API_KEY 或其他供应商的密钥

# 部署
sudo bash deploy.sh
```

脚本做的事（幂等，可重复执行）：

1. 安装 python3 / nginx
2. 建虚拟环境并装依赖
3. 检查模型文件，缺失则自动下载
4. 注册 systemd 服务（单进程，监听 `127.0.0.1:8001`）
5. 配置 nginx 反代（已针对 SSE 关闭缓冲）
6. 启动并通过 `/health` 自检

常用参数：

```bash
sudo bash deploy.sh --no-deps            # 只更新服务配置，不重装依赖
sudo PORT=8080 bash deploy.sh            # 换端口
sudo APP_USER=www-data bash deploy.sh    # 换运行用户
```

## 2. 模型文件怎么下

### 方式 A：浏览器下载（大文件推荐）

国内直连 `huggingface.co` 通常不通，用镜像站，浏览器打开：

```
https://hf-mirror.com/BAAI/bge-reranker-base/tree/main
```

下载这几个文件（点文件名右侧的下载箭头）：

| 文件 | 大小 | 说明 |
|---|---|---|
| `model.safetensors` | 1060.7 MB | 权重，最大也最关键 |
| `tokenizer.json` | 16.3 MB | |
| `sentencepiece.bpe.model` | 4.8 MB | |
| `config.json` | 小 | |
| `tokenizer_config.json` | 小 | |
| `special_tokens_map.json` | 小 | |

`pytorch_model.bin` 与 `model.safetensors` 是同一份权重的两种格式，
**只需要下其中一个**。

向量模型同理，文件更小：

```
https://hf-mirror.com/BAAI/bge-small-zh-v1.5/tree/main
```

需要：`pytorch_model.bin`(91.4 MB)、`config.json`、`modules.json`、
`sentence_bert_config.json`、`special_tokens_map.json`、`tokenizer.json`、
`tokenizer_config.json`、`vocab.txt`，以及子目录里的 `1_Pooling/config.json`
（子目录结构要保持）。

传到服务器后按原目录结构放好：

```
/opt/agri-kb-v4/models/
├── bge-reranker-base/
│   ├── config.json
│   ├── model.safetensors
│   ├── tokenizer.json
│   └── ...
└── bge-small-zh-v1.5/
    ├── config.json
    ├── pytorch_model.bin
    ├── 1_Pooling/config.json
    └── ...
```

然后在 `.env` 里**直接指向目录**（程序识别到是目录就不会联网）：

```dotenv
EMBED_MODEL=/opt/agri-kb-v4/models/bge-small-zh-v1.5
RERANK_ENABLED=true
RERANK_MODEL=/opt/agri-kb-v4/models/bge-reranker-base
```

验证：

```bash
source venv/bin/activate
python -m app.tools.prefetch_models --check
```

### 方式 B：命令行下载

```bash
source venv/bin/activate
python -m app.tools.prefetch_models                  # 两个模型都下
python -m app.tools.prefetch_models --rerank-only    # 只下重排模型
```

支持断点续传，失败或卡住时重跑即可，会从断点继续。

## 3. 配置 HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d kb.example.com
```

certbot 会自动改写 nginx 配置加上 443 与证书路径，
原有的 `proxy_buffering off` 等设置会保留。

## 4. 日常更新与回滚

更新：

```bash
cd /opt/agri-kb-v4
sudo git pull
sudo bash deploy.sh --no-deps      # 依赖没变时用这个，几秒完成
```

`requirements.txt` 有变化时去掉 `--no-deps`。

回滚：

```bash
cd /opt/agri-kb-v4
sudo git log --oneline -10
sudo git checkout <提交的 SHA>
sudo bash deploy.sh --no-deps
sudo git checkout main             # 想回到最新版
```

## 5. 运维

```bash
systemctl status agri-kb            # 服务状态
journalctl -u agri-kb -f            # 实时日志
journalctl -u agri-kb --since "1 hour ago"
curl localhost:8001/health          # 健康检查
```

健康检查返回索引规模、向量/重排是否就绪、当前模型：

```json
{"status":"ok","documents":21,"chunks":47,"sessions":3,
 "embedding_ready":true,"llm":{"provider":"deepseek","configured":true}}
```

### 数据与备份

```
data/conversations.json     会话历史
data/feedback.sqlite3       用户反馈
data/embedding_cache.npz    向量缓存（可重建，不必备份）
data/hf_cache/              模型文件（可重建，不必备份）
knowledge_base/             知识库原文
uploads/                    用户上传的文档
```

备份只需 `data/` 下的 json 与 sqlite3、`knowledge_base/`、`uploads/`。

### 日志占用

日志走 journald，默认已有轮转。限制占用：

```bash
sudo journalctl --vacuum-size=200M
```

或在 `/etc/systemd/journald.conf` 中设置 `SystemMaxUse=200M`。

## 6. 排障

**服务起不来，`status=203/EXEC`，日志报 `Failed to locate executable .../venv/bin/uvicorn`**：
venv 里没有依赖。**`--no-deps` 只能在依赖装好之后用**，否则会把一个空的 venv
留给 systemd。补装即可：

```bash
source /opt/agri-kb/venv/bin/activate
pip install -r /opt/agri-kb/requirements.txt
sudo systemctl restart agri-kb
```

> 脚本现在会在**动 systemd 之前**做启动前自检（uvicorn 是否存在、
> 能否 `import main`），不通过就直接退出且不碰现有服务；
> 覆盖 unit 文件与 nginx 配置前也会自动备份带时间戳的副本。

**nginx 警告 `conflicting server name "_"`**：`sites-enabled/` 里有另一个站点
也用了 `server_name _`，nginx 只会生效其中一个，本项目的配置可能被忽略。
查看并处理：

```bash
grep -rn "server_name" /etc/nginx/sites-enabled/
# 停用旧站点： sudo rm /etc/nginx/sites-enabled/那个文件 && sudo systemctl reload nginx
```

**`from versions: none`**：pip 连得上索引，但认为没有任何版本的包适用于当前
Python。绝大多数情况是**系统 Python 太老**（Ubuntu 18.04 自带 3.6，
而 fastapi 全系列要求 ≥3.7）。执行 `python3 --version` 确认，
然后按脚本开头给出的两条路径之一处理：装新版 Python 后用
`PYTHON=python3.11 bash deploy.sh` 重新执行，或直接换成 Ubuntu 22.04/24.04。

> 注意：`venv` 目录建过之后不能换 Python 复用，升级 Python 前要先 `rm -rf venv`。

**依赖装不上 / `from versions: none`（Python 版本正常时）**：
**云服务器不要覆盖 pip 索引**。阿里云 ECS 的 `/etc/pip.conf` 通常已指向内网
镜像 `mirrors.cloud.aliyuncs.com`，免流量费且更快；显式传 `-i <别的源>`
会覆盖它，反而可能连不上（实测清华源对部分机房返回 403）。
`deploy.sh` 默认尊重系统配置，依次尝试：显式指定 → 系统配置 → 清华 → 官方。

排查时注意：`curl -I`（HEAD 请求）常被镜像站拒绝，要测连通性请用 GET：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://mirrors.cloud.aliyuncs.com/pypi/simple/fastapi/
```

需要换源时显式指定：`sudo PIP_INDEX=https://pypi.org/simple bash deploy.sh`

**页面打不开**：先 `curl localhost:8001/health` 看后端有没有响应。
后端只监听 `127.0.0.1`，必须经 nginx 访问。

**回答不是逐字出现的**：nginx 少了 `proxy_buffering off`。
重跑 `sudo bash deploy.sh --no-deps` 会覆盖回正确配置。

**模型下载失败或卡住**：改用上面的浏览器方式。

**报 CUDA / GPU 相关错误**：本项目纯 CPU 推理，说明装成了 GPU 版 torch，
重装 CPU 版即可。

**进程被 OOM Killer 杀掉**：`journalctl -u agri-kb | grep -i kill` 确认。
加内存，或在 `.env` 里设 `EMBED_ENABLED=false` 退化到纯 BM25。
