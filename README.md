# agri-kb · 新疆农业知识库 RAG 问答系统

面向新疆农业场景的检索增强问答服务：从 20 余篇专业文档中检索相关片段，
交给大模型生成有据可依的回答，并通过 SSE 逐字推送到网页。

## 架构

```
                        ┌──────────────────────────────┐
   浏览器  ──HTTP/SSE──▶ │  app/api/     传输层          │
                        │  chat / documents / session   │
                        └──────────────┬───────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            ▼                          ▼                          ▼
   ┌─────────────────┐      ┌──────────────────┐      ┌──────────────────┐
   │ retrieval/      │      │ llm/             │      │ session/         │
   │ 混合检索引擎     │      │ 供应商适配层      │      │ 会话存储          │
   │ BM25 + 向量      │      │ DeepSeek / 神农… │      │ JSON / SQLite    │
   └────────┬────────┘      └──────────────────┘      └──────────────────┘
            │
   ┌────────▼────────┐      ┌──────────────────┐
   │ ingest/         │      │ core/            │
   │ 文档仓库与解析    │      │ 提示词 / 日志     │
   └─────────────────┘      └──────────────────┘
```

依赖方向自上而下，下层不反向依赖上层。配置集中在 `app/config.py`，
应用装配在 `app/factory.py`，其余模块只关心自己的职责。

## 目录结构

```
app/
  config.py              配置中心（.env 与环境变量）
  factory.py             应用工厂 + 生命周期
  schemas.py             API 出入参模型
  api/                   HTTP 路由：deps / chat / documents / session / meta / pages
  core/                  提示词模板、日志
  retrieval/             分词、分块、BM25、向量、混合检索引擎
  ingest/                文档解析器（txt/md/pdf/docx）与文档仓库
  llm/                   供应商抽象、OpenAI 兼容实现、预设与工厂
  session/               会话存储抽象（JSON / SQLite）
knowledge_base/          知识库源文档
uploads/                 用户上传文档
data/                    运行期数据（会话、向量缓存），已加入 .gitignore
static/ templates/       前端资源
tests/smoke_test.py      端到端冒烟测试
main.py                  启动入口（仅创建应用实例）
```

## 快速开始

```bash
conda activate rag
pip install -r requirements.txt

# 配置密钥
cp .env.example .env      # 填入 DEEPSEEK_API_KEY

# 启动
uvicorn main:app --host 0.0.0.0 --port 8000
# 或
python main.py
```

打开 http://localhost:8000 即可使用。

## 更换大模型供应商

业务代码只依赖 `app/llm/base.py` 中的 `LLMProvider` 接口，换模型只需改 `.env`。

### 换成神农大模型（中国农业大学）

神农大模型是农业垂直领域模型，**本项目已接通并验证**：接口为 OpenAI 兼容，
支持 SSE 流式输出。在 `.env` 里填三行即可：

```dotenv
LLM_PROVIDER=shennong
SHENNONG_BASE_URL=https://api.agent-tech.cc/api/v1
SHENNONG_MODEL=sn
SHENNONG_API_KEY=<密钥>
```

前两项已作为预设内置，实际只需提供 `SHENNONG_API_KEY`。若对接方另有内网
地址，用 `SHENNONG_BASE_URL` 覆盖即可。如果对方是私有协议，只需在
`app/llm/` 下新增一个实现类，并在 `app/llm/registry.py` 里加一个分支，
其余代码不用动。

### 其它可选供应商

| key | 说明 |
|---|---|
| `deepseek` | 默认供应商 |
| `shennong` | 神农大模型，需自备接入信息 |
| `qwen` | 通义千问（阿里云百炼），OpenAI 兼容模式 |
| `zhipu` | 智谱 GLM |
| `moonshot` | 月之暗面 Kimi |
| `ollama` | 本地推理，适合内网/离线部署 |
| `custom` | 任意 OpenAI 兼容服务，填 `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` |

查看当前生效的供应商与全部可选项：`GET /api/providers`。

## 检索原理

1. **分块**：长文档按换行与句号切成约 400 字的片段；
2. **粗排**：BM25 关键词打分，召回 `top_k × 3` 个候选；
3. **精排**：BGE 中文向量模型（`bge-small-zh-v1.5`，约 24MB）算语义相似度；
4. **融合**：BM25 分数先做 min-max 归一化，再按 `0.3 / 0.7` 加权；
5. **去重**：单篇文档最多贡献 2 个片段，保证参考来源多样化。

向量模型在服务启动后于后台线程预热，不阻塞启动；模型不可用时自动降级为
纯 BM25，服务照常可用。国内网络请设置 `HF_ENDPOINT=https://hf-mirror.com`。

## 会话存储

| | JSON（默认） | SQLite |
|---|---|---|
| 写入 | 全文件覆写（临时文件 + 原子替换） | 只追加行 |
| 并发 | 进程内加锁 | WAL 模式，支持并发读写 |
| 崩溃恢复 | 原子替换保证不写坏 | 事务回滚 |
| 适用 | 个人使用、便于查看 | 多人使用、数据量大 |

切换只需在 `.env` 中设置 `SESSION_BACKEND=sqlite`。旧版 `conversations.json`
会在首次启动时自动迁移到 `data/` 目录。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 前端页面 |
| GET | `/api/documents` | 文档列表 |
| GET | `/api/document/{filename}` | 文档全文 |
| POST | `/api/upload` | 上传文档（txt/md/pdf/docx） |
| DELETE | `/api/document/{filename}` | 删除上传的文档 |
| POST | `/api/chat/stream` | 流式问答（SSE） |
| POST | `/api/session/reset` | 清空会话 |
| GET | `/api/session/{id}` | 取会话历史 |
| GET | `/api/stats` | 系统统计 |
| GET | `/api/providers` | 供应商信息 |
| GET | `/health` | 健康检查 |

SSE 事件格式：`sources` → 若干 `chunk` → `[DONE]`，出错时推送 `error`。

## 配置项

全部配置项见 `.env.example`，常用几项：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_PROVIDER` | `deepseek` | 供应商 |
| `LLM_MAX_RETRIES` | `2` | 瞬时网络故障自动重试次数 |
| `LLM_CONNECT_TIMEOUT` | `5` | 建连超时（秒） |
| `LLM_KEEPALIVE_EXPIRY` | `300` | 长连接复用时长（秒） |
| `RAG_TOP_K` | `5` | 送入模型的参考片段数 |
| `RAG_MIN_CHUNK_SIZE` | `80` | 小于该长度的碎片并入相邻片段 |
| `RAG_BM25_WEIGHT` / `RAG_EMBED_WEIGHT` | `0.3` / `0.7` | 融合权重 |
| `EMBED_ENABLED` | `true` | 关掉即退化为纯 BM25 |
| `RERANK_ENABLED` | `false` | 是否启用重排（需先下载模型） |
| `SESSION_BACKEND` | `json` | `json` 或 `sqlite` |
| `SESSION_MAX` | `100` | 会话数上限，超出淘汰最旧的 |

## 测试

```bash
python tests/smoke_test.py
```

覆盖文档接口、检索引擎、SSE 流式问答、会话持久化与重启恢复、健康检查，
全程不联网、无需 pytest。

## 检索评测

改检索参数最怕「凭感觉调」。`tests/eval_retrieval.py` 用一套标注过的题目
给出可对比的数字：

```bash
python tests/eval_retrieval.py                # 当前配置
python tests/eval_retrieval.py --no-embed     # 关掉向量做对照
python tests/eval_retrieval.py --top-k 3      # 换 recall@3
python tests/eval_retrieval.py --json a.json  # 落盘，便于前后对比
```

题目在 `tests/eval_set.json`，直接加题即可。题目分两类：
`direct`（用词贴近文档原文）和 `colloquial`（口语化提问），
**后者才是真正考验语义检索的部分**，调参时重点看它的 MRR。

当前基线（30 题，chunk=400 / min=80）：

```
recall@5 = 29/30 = 97%     MRR = 0.864
  colloquial   9/10 =  90%   MRR = 0.692
  direct       20/20 = 100%  MRR = 0.950
```

消融对照（同一套题）：

| 配置 | recall@5 | MRR |
|---|---|---|
| 纯 BM25 | 97% | 0.798 |
| BM25 + 向量 | 97% | 0.886 |

可以看到向量层主要提升的是**排序质量**（MRR +0.088）而不是召回率——
也就是让正确的文档排得更靠前。

## 重排（可选，推荐）

召回用的双塔模型只能算「大致相关」，重排模型（cross-encoder）会把问题和
每个候选片段拼在一起精细打分，把真正回答了问题的片段顶到前面，是 RAG 里
公认收益最大的一步。

重排模型约 1GB，**默认关闭**——不适合让服务在启动时悄悄拉。启用步骤：

```bash
python -m app.tools.prefetch_models --rerank-only   # 先下好（支持断点续传）
# 然后在 .env 中设置 RERANK_ENABLED=true 并重启
```

轻量替代：`RERANK_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`（约 470MB）。
模型未就绪时重排自动跳过，检索照常工作。

## 用户反馈

每条回答下方的 👍 / 👎 会记到 `data/feedback.sqlite3`：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/feedback` | 提交评价 |
| GET | `/api/feedback/stats` | 好评率概览 |
| GET | `/api/feedback/recent?rating=down` | 捞出点踩的案例复盘 |

点踩的案例是「当前检索或提示词做得不好」的真实样本，
直接补进 `tests/eval_set.json` 就变成了回归测试题。

## 常见问题

**浏览器打不开页面**：日志里 uvicorn 打印的 `http://0.0.0.0:8000` 是监听地址，
不是可以访问的地址，请在浏览器里用 **http://127.0.0.1:8000**。
如果 `http://localhost:8000` 打不开，是因为 `localhost` 在 Windows 上优先解析为
IPv6 的 `::1`，而服务只监听了 IPv4；改用 `127.0.0.1`，或加 `--host ::` 监听双栈。

**前端不依赖任何 CDN**：Markdown 由 `app.js` 内置渲染器处理，断网或纯内网
环境都能正常显示。如果自行引入了 `marked`，代码会自动优先使用它。

**启动时日志刷 HuggingFace 请求**：模型已缓存时会直接读本地快照，不会联网；
首次下载请确认 `HF_ENDPOINT` 指向可用镜像。

**模型调用失败但错误信息是空的**：这是 `httpx` 超时类异常的特性（`str()` 返回
空字符串），已在 `describe_http_error()` 中翻译成可读原因并带上底层错误码，
同时瞬时的超时/断连会自动重试一次。

**偶发「无法建立连接」**：教育网线路（如神农的 `202.205.91.148`）存在约 5%
的 TCP 握手丢包，成功的连接只需 0.1 秒，丢包的那次会一直挂到超时。项目已用
「短连接超时 + 自动重试 + 长连接复用」消化掉：握手只在首次或连接空闲过期后
发生，失败会自动重试，实测 30 次连续请求 30/30 成功。如果频繁出现，属于
线路质量问题，可向对接方反馈。

**`conda activate` 后仍是 base 环境**：PowerShell 需要先执行一次
`conda init powershell`，然后重开终端。

**向量模型下载失败**：`HF_ENDPOINT=https://hf-mirror.com` 已默认写入
`.env.example`；镜像也连不上时设 `EMBED_ENABLED=false`，检索自动降级。

**接口返回 500 且提示 `unhashable type: 'dict'`**：Starlette 1.x 要求
`TemplateResponse(request=..., name=...)`，本项目已适配。
