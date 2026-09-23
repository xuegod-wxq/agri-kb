
// ===== DOM Elements =====
const chatMessages = document.getElementById("chat-messages");
const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const stopBtn = document.getElementById("stop-btn");
const fileUpload = document.getElementById("file-upload");
const kbList = document.getElementById("kb-list");
const kbSearch = document.getElementById("kb-search");
const sidebarStats = document.getElementById("sidebar-stats");
const statusEl = document.getElementById("status");
const sidebar = document.getElementById("sidebar");
const menuToggle = document.getElementById("menu-toggle");
const modalOverlay = document.getElementById("modal-overlay");
const modalTitle = document.getElementById("modal-title");
const modalBody = document.getElementById("modal-body");
const modalClose = document.getElementById("modal-close");
const statsOverlay = document.getElementById("stats-overlay");
const statsBody = document.getElementById("stats-body");
const statsClose = document.getElementById("stats-close");
const statsBtn = document.getElementById("stats-btn");
const themeToggle = document.getElementById("theme-toggle");
const aboutLink = document.getElementById("about-link");
const clearChatBtn = document.getElementById("clear-chat");
const exportChatBtn = document.getElementById("export-chat");
const suggestions = document.getElementById("suggestions");

// 使用 localStorage 持久化 sessionId，刷新后能恢复对话上下文
let sessionId = localStorage.getItem("agri_session_id") || "sess_" + Date.now();
localStorage.setItem("agri_session_id", sessionId);
let isLoading = false;
let allDocs = [];
let abortController = null;
let questionCount = 0;

// ===== 推荐问题题库（每次随机选4个）=====
const SUGGESTION_POOL = [
    { emoji: "💧", q: "棉花蕾期含水量低于多少需要灌溉？", label: "棉花蕾期灌溉条件" },
    { emoji: "🐛", q: "棉铃虫怎么识别和防治？", label: "棉铃虫识别与防治" },
    { emoji: "🍅", q: "加工番茄果实膨大期怎么施肥？", label: "番茄膨大期施肥方案" },
    { emoji: "🔧", q: "滴灌系统压力不足怎么排查？", label: "滴灌系统故障排查" },
    { emoji: "🌾", q: "冬小麦返青期水肥管理要点？", label: "冬小麦返青期管理" },
    { emoji: "🌿", q: "棉花花铃期如何管理？", label: "棉花花铃期管理" },
    { emoji: "🪴", q: "新疆盐碱地怎么改良？", label: "盐碱地改良方法" },
    { emoji: "🌡️", q: "大棚温度过高怎么降温？", label: "温室降温措施" },
    { emoji: "💊", q: "棉花蚜虫用什么药剂防治？", label: "蚜虫药剂防治" },
    { emoji: "📡", q: "土壤墒情传感器怎么布设？", label: "传感器布设方案" },
    { emoji: "🌧️", q: "霜冻来临前应采取什么防护措施？", label: "霜冻防护措施" },
    { emoji: "🍎", q: "红枣树修剪有哪些注意事项？", label: "红枣树修剪技术" },
    { emoji: "🌽", q: "玉米制种田隔离距离多少合适？", label: "玉米制种隔离要求" },
    { emoji: "💦", q: "膜下滴灌每亩用水量怎么计算？", label: "滴灌用水量计算" },
    { emoji: "🧪", q: "水肥一体化氮磷钾比例怎么配？", label: "水肥配比方案" },
    { emoji: "🦗", q: "红蜘蛛爆发前有什么预警信号？", label: "红蜘蛛预警信号" },
    { emoji: "🌤️", q: "高温热害对棉花产量有什么影响？", label: "高温热害影响" },
    { emoji: "🏠", q: "日光温室冬季保温有哪些措施？", label: "温室冬季保温" },
    { emoji: "📊", q: "棉花产量预测模型怎么建立？", label: "产量预测模型" },
    { emoji: "🔌", q: "智能灌溉控制器怎么配置？", label: "智能灌溉配置" },
    { emoji: "🌱", q: "棉花播种前底肥怎么施？", label: "棉花底肥方案" },
    { emoji: "🪲", q: "棉铃虫最佳防治时期是什么时候？", label: "棉铃虫防治时期" },
    { emoji: "💧", q: "滴灌带堵塞怎么清理？", label: "滴灌带堵塞清理" },
    { emoji: "🍇", q: "葡萄水肥管理有哪些关键期？", label: "葡萄水肥管理" },
];

function getRandomSuggestions(n) {
    n = n || 4;
    var pool = SUGGESTION_POOL.slice();  // 浅拷贝
    // Fisher-Yates 洗牌
    for (var i = pool.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1));
        var tmp = pool[i]; pool[i] = pool[j]; pool[j] = tmp;
    }
    return pool.slice(0, n);
}

function buildSuggestionHTML() {
    var items = getRandomSuggestions(4);
    var html = "";
    items.forEach(function(s) {
        html += '<div class="sug-card" data-q="' + escAttr(s.q) + '">' + s.emoji + ' ' + escHtml(s.label) + '</div>';
    });
    return html;
}

// ===== Dark Mode =====
function initTheme() {
    const saved = localStorage.getItem("theme");
    if (saved === "dark") {
        document.documentElement.setAttribute("data-theme", "dark");
        themeToggle.textContent = "☀️";
    }
}
initTheme();
themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    if (current === "dark") {
        document.documentElement.removeAttribute("data-theme");
        themeToggle.textContent = "🌙";
        localStorage.setItem("theme", "light");
    } else {
        document.documentElement.setAttribute("data-theme", "dark");
        themeToggle.textContent = "☀️";
        localStorage.setItem("theme", "dark");
    }
});

// ===== Sidebar =====
menuToggle.addEventListener("click", () => sidebar.classList.toggle("open"));
document.addEventListener("click", (e) => {
    if (!sidebar.contains(e.target) && e.target !== menuToggle && sidebar.classList.contains("open"))
        sidebar.classList.remove("open");
});

// Mobile swipe to close
let touchStartX = 0;
sidebar.addEventListener("touchstart", (e) => {
    touchStartX = e.touches[0].clientX;
}, {passive: true});
sidebar.addEventListener("touchmove", (e) => {
    const dx = e.touches[0].clientX - touchStartX;
    if (dx < -60) sidebar.classList.remove("open");
}, {passive: true});

// ===== Modal =====
modalClose.addEventListener("click", closeModal);
modalOverlay.addEventListener("click", (e) => { if (e.target === modalOverlay) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && modalOverlay.style.display === "flex") closeModal(); });

// ===== Stats Overlay =====
statsBtn.addEventListener("click", openStats);
statsClose.addEventListener("click", () => { statsOverlay.style.display = "none"; });
statsOverlay.addEventListener("click", (e) => { if (e.target === statsOverlay) statsOverlay.style.display = "none"; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && statsOverlay.style.display === "flex") statsOverlay.style.display = "none"; });

// ===== About Link =====
aboutLink.addEventListener("click", openAbout);

// ===== Search =====
kbSearch.addEventListener("input", () => renderKbList(allDocs, kbSearch.value));

// ===== Upload =====
fileUpload.addEventListener("change", handleFileUpload);

// ===== Chat =====
sendBtn.addEventListener("click", () => sendMessage());
stopBtn.addEventListener("click", stopGeneration);
userInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
userInput.addEventListener("input", () => {
    userInput.style.height = "auto";
    userInput.style.height = Math.min(userInput.scrollHeight, 120) + "px";
});

// Clear chat
clearChatBtn.addEventListener("click", async () => {
    try {
        await fetch("/api/session/reset", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: "", session_id: sessionId })
        });
    } catch (_) {}
    sessionId = "sess_" + Date.now();
    localStorage.setItem("agri_session_id", sessionId);
    questionCount = 0;
    chatMessages.innerHTML = buildWelcomeHTML();
    reattachSuggestions();
    setStatus("就绪");
});

// Export chat
exportChatBtn.addEventListener("click", exportChat);

// Suggested questions
if (suggestions) {
    suggestions.addEventListener("click", (e) => {
        const card = e.target.closest(".sug-card");
        if (!card) return;
        const q = card.getAttribute("data-q");
        if (q) {
            userInput.value = q;
            sendMessage();
        }
    });
}


// ===== Send Message (with AbortController) =====
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text || isLoading) return;
    userInput.value = "";
    userInput.style.height = "auto";

    // Remove welcome message if present
    const welcomeMsg = chatMessages.querySelector(".welcome-msg");
    if (welcomeMsg) welcomeMsg.remove();

    addUserMsg(text);
    questionCount++;
    isLoading = true;
    sendBtn.disabled = true;
    sendBtn.style.display = "none";
    stopBtn.style.display = "inline-block";
    userInput.disabled = true;

    const msgDiv = addAssistantMsg();
    const contentDiv = msgDiv.querySelector(".msg-content");
    const sourcesDiv = msgDiv.querySelector(".msg-sources");
    const copyBtn = msgDiv.querySelector(".copy-btn");
    let fullText = "";
    let fullSources = [];
    let cursor = null;
    setStatus("思考中...");

    abortController = new AbortController();

    try {
        const resp = await fetch("/api/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text, session_id: sessionId }),
            signal: abortController.signal
        });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";
            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                const dataStr = line.slice(6);
                if (dataStr === "[DONE]") break;
                try {
                    const ev = JSON.parse(dataStr);
                    if (ev.type === "sources" && ev.data) {
                        fullSources = ev.data;
                        sourcesDiv.innerHTML = fullSources.map(s => "<span class=\"src-link\" data-doc=\"" + escAttr(s.filename) + "\">" + escHtml(s.filename) + "</span>").join(" ");
                    } else if (ev.type === "chunk") {
                        fullText += ev.data;
                        contentDiv.innerHTML = renderMarkdown(fullText);
                        if (!cursor) {
                            cursor = document.createElement("span");
                            cursor.className = "typing-cursor";
                            contentDiv.appendChild(cursor);
                        }
                        chatMessages.scrollTop = chatMessages.scrollHeight;
                    } else if (ev.type === "error") {
                        contentDiv.innerHTML = escHtml(ev.data);
                    }
                } catch (_) {}
            }
        }
    } catch (err) {
        if (err.name === "AbortError") {
            if (!fullText) {
                contentDiv.innerHTML = "<em>已停止生成</em>";
            }
        } else {
            contentDiv.innerHTML = "连接错误: " + escHtml(err.message);
        }
    }

    abortController = null;
    if (cursor) cursor.remove();
    if (fullText) {
        contentDiv.innerHTML = renderMarkdown(fullText);
        copyBtn.style.display = "block";
        copyBtn.onclick = () => copyText(fullText, copyBtn);
    } else if (contentDiv.innerHTML === "") {
        contentDiv.innerHTML = "（无内容）";
    }
    chatMessages.scrollTop = chatMessages.scrollHeight;
    setStatus("就绪");
    finishLoading();

    // 挂上元信息，供 👍/👎 提交反馈时使用
    msgDiv._feedback = {
        question: text,
        answer: fullText,
        sources: fullSources.map(function (s) { return s.filename; })
    };
}

function stopGeneration() {
    if (abortController) {
        abortController.abort();
        abortController = null;
    }
    finishLoading();
    setStatus("就绪");
}

function finishLoading() {
    isLoading = false;
    sendBtn.disabled = false;
    sendBtn.style.display = "inline-block";
    stopBtn.style.display = "none";
    userInput.disabled = false;
    userInput.focus();
}


// ===== Knowledge Base =====
async function loadKnowledgeBase() {
    try {
        const r = await fetch("/api/documents");
        const data = await r.json();
        allDocs = Array.isArray(data) ? data : (data.documents || []);
        renderKbList(allDocs, kbSearch.value);
        updateSidebarStats();
    } catch (e) {
        kbList.innerHTML = '<p class="loading-hint">加载失败</p>';
    }
}

function updateSidebarStats() {
    const totalDocs = allDocs.length;
    let totalChunks = 0;
    allDocs.forEach(d => {
        if (d.size !== undefined) totalChunks += Math.ceil(d.size / 400) || 1;
    });
    sidebarStats.textContent = "📚 " + totalDocs + " 篇文档 · " + totalChunks + " 个知识块";
}

function renderKbList(docs, filter) {
    const f = (filter || "").toLowerCase();
    let filtered = docs;
    if (f) {
        filtered = docs.filter(d =>
            (d.title || d.name || d.filename || "").toLowerCase().includes(f)
        );
    }

    const categories = {};
    const catOrder = ["棉花", "番茄", "小麦", "玉米", "灌溉与水肥", "病虫害防治", "土壤与施肥", "气象与防灾", "智能设备", "设备与故障", "果树栽培", "设施农业", "作物模型", "其他文档"];
    const emojiMap = {
        "棉花": "🌿", "番茄": "🍅", "小麦": "🌾", "玉米": "🌽",
        "灌溉与水肥": "💧", "病虫害防治": "🐛", "土壤与施肥": "🪴",
        "气象与防灾": "🌤️", "智能设备": "📡", "设备与故障": "🔧",
        "果树栽培": "🍎", "设施农业": "🏠", "作物模型": "📊", "其他文档": "📄"
    };

    filtered.forEach(d => {
        const name = d.title || d.name || d.filename || "其他";
        let cat = "其他文档";
        if (name.includes("棉花") || name.includes("cotton")) cat = "棉花";
        else if (name.includes("番茄") || name.includes("tomato")) cat = "番茄";
        else if (name.includes("小麦") || name.includes("wheat")) cat = "小麦";
        else if (name.includes("玉米") || name.includes("corn")) cat = "玉米";
        else if (name.includes("灌溉") || name.includes("irrigation") || name.includes("水") || name.includes("water") || name.includes("滴灌") || name.includes("drip")) cat = "灌溉与水肥";
        else if (name.includes("病虫害") || name.includes("pest") || name.includes("虫")) cat = "病虫害防治";
        else if (name.includes("土壤") || name.includes("soil") || name.includes("盐碱") || name.includes("salinity") || name.includes("施肥") || name.includes("fertilization")) cat = "土壤与施肥";
        else if (name.includes("天气") || name.includes("weather") || name.includes("霜冻") || name.includes("frost")) cat = "气象与防灾";
        else if (name.includes("传感器") || name.includes("sensor") || name.includes("smart")) cat = "智能设备";
        else if (name.includes("设备") || name.includes("equipment") || name.includes("故障")) cat = "设备与故障";
        else if (name.includes("果树") || name.includes("fruit") || name.includes("红枣") || name.includes("葡萄")) cat = "果树栽培";
        else if (name.includes("温室") || name.includes("greenhouse")) cat = "设施农业";
        else if (name.includes("作物") || name.includes("crop")) cat = "作物模型";
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(d);
    });

    let html = "";
    catOrder.forEach(cat => {
        const items = categories[cat];
        if (!items || items.length === 0) return;
        html += '<div class="kb-category">';
        html += '<div class="kb-cat-title">' + (emojiMap[cat] || "📄") + " " + cat + "</div>";
        items.forEach(d => {
            const name = d.title || d.name || d.filename || "未知";
            const icon = name.endsWith(".docx") || name.endsWith(".doc") ? "📝" :
                         name.endsWith(".pdf") ? "📕" : "📄";
            html += "<div class=\"kb-item\" data-doc=\"" + escAttr(d.filename) + "\">";
            html += '<span class="kb-icon">' + icon + "</span>";
            html += '<span class="kb-name">' + escHtml(name) + "</span>";
            html += "</div>";
        });
        html += "</div>";
    });
    kbList.innerHTML = html || '<p class="loading-hint">无匹配文档</p>';
}

// ===== Document Modal =====
async function openDoc(filename) {
    try {
        const r = await fetch("/api/document/" + encodeURIComponent(filename));
        if (!r.ok) throw new Error("Not found");
        const doc = await r.json();
        if (doc && doc.content) {
            modalTitle.textContent = doc.name || doc.filename;
            modalBody.innerHTML = renderMarkdown(doc.content);
        } else {
            modalTitle.textContent = filename;
            modalBody.innerHTML = "<p>文档内容不可用</p>";
        }
        modalOverlay.style.display = "flex";
    } catch (e) {
        modalTitle.textContent = "错误";
        modalBody.innerHTML = "<p>加载文档失败: " + escHtml(e.message) + "</p>";
        modalOverlay.style.display = "flex";
    }
}

function closeModal() {
    modalOverlay.style.display = "none";
}

// ===== About Modal =====
function openAbout() {
    modalTitle.textContent = "关于知识库";
    modalBody.innerHTML = '<h2>知识来源与权威性说明</h2>' +
        '<p>本知识库内容基于以下权威来源整理：</p>' +
        '<ul>' +
        '<li><strong>《新疆主要农作物栽培技术规程》</strong> — 新疆生产建设兵团农业技术推广总站</li>' +
        '<li><strong>《膜下滴灌技术规范》(GB/T 50485)</strong> — 国家标准化管理委员会</li>' +
        '<li><strong>《新疆棉花高产优质栽培技术》</strong> — 石河子大学农学院</li>' +
        '<li><strong>《新疆加工番茄栽培技术规程》(DB65/T 2894)</strong> — 新疆维吾尔自治区质量技术监督局</li>' +
        '<li><strong>《主要农作物病虫害测报技术规范》</strong> — 全国农业技术推广服务中心</li>' +
        '<li><strong>《日光温室结构标准》(GB/T 19165)</strong> — 国家标准化管理委员会</li>' +
        '</ul>' +
        '<h3>局限性声明</h3>' +
        '<ul>' +
        '<li>知识库涵盖新疆兵团主要作物和农业技术，但<strong>不替代专业农技人员现场诊断</strong></li>' +
        '<li>病虫害识别建议仅供参考，大面积爆发时应联系当地植保站</li>' +
        '<li>施肥配方基于通用标准，具体用量需根据土壤检测结果调整</li>' +
        '<li>气象数据阈值参考近10年新疆气候特征，极端年份可能不适用</li>' +
        '<li>AI 回答由 DeepSeek 大模型结合知识库生成，可能含有不准确信息</li>' +
        '</ul>' +
        '<h3>更新频率</h3>' +
        '<p>知识库随新疆农业技术标准的更新同步维护，建议每年春耕前进行复核。</p>' +
        '<p style="margin-top:16px;color:var(--text-tertiary);font-size:12px;">版本 v4.2 · 20 篇专业文档 · BM25 语义检索</p>';
    modalOverlay.style.display = "flex";
}

// ===== Stats =====
function openStats() {
    const catCount = {};
    allDocs.forEach(d => {
        const name = d.title || d.name || d.filename || "其他";
        let cat = "其他";
        if (name.includes("棉花") || name.includes("cotton")) cat = "棉花";
        else if (name.includes("番茄") || name.includes("tomato")) cat = "番茄";
        else if (name.includes("小麦") || name.includes("wheat")) cat = "小麦";
        else if (name.includes("玉米") || name.includes("corn")) cat = "玉米";
        else if (name.includes("灌溉") || name.includes("水") || name.includes("滴灌") || name.includes("drip") || name.includes("水肥") || name.includes("fertigation")) cat = "灌溉与水肥";
        else if (name.includes("病虫害") || name.includes("pest") || name.includes("虫")) cat = "病虫害防治";
        else if (name.includes("土壤") || name.includes("soil") || name.includes("施肥") || name.includes("fertilization") || name.includes("盐碱") || name.includes("salinity")) cat = "土壤与施肥";
        else if (name.includes("天气") || name.includes("weather") || name.includes("霜冻") || name.includes("frost")) cat = "气象与防灾";
        else if (name.includes("传感器") || name.includes("sensor") || name.includes("smart")) cat = "智能设备";
        else if (name.includes("设备") || name.includes("equipment") || name.includes("故障")) cat = "设备与故障";
        else if (name.includes("果树") || name.includes("fruit") || name.includes("红枣") || name.includes("葡萄")) cat = "果树栽培";
        else if (name.includes("温室") || name.includes("greenhouse")) cat = "设施农业";
        else if (name.includes("作物") || name.includes("crop")) cat = "作物模型";
        catCount[cat] = (catCount[cat] || 0) + 1;
    });

    const sortedCats = Object.entries(catCount).sort((a, b) => b[1] - a[1]);
    let catRows = "";
    sortedCats.forEach(([k, v]) => {
        catRows += '<div class="stat-row"><span class="stat-key">' + escHtml(k) + '</span><span class="stat-val">' + v + ' 篇</span></div>';
    });

    statsBody.innerHTML = '<div class="stats-grid">' +
        '<div class="stat-card"><div class="stat-num">' + allDocs.length + '</div><div class="stat-label">知识文档总数</div></div>' +
        '<div class="stat-card"><div class="stat-num">' + questionCount + '</div><div class="stat-label">本轮提问次数</div></div>' +
        '<div class="stat-card"><div class="stat-num">BM25</div><div class="stat-label">检索算法</div></div>' +
        '<div class="stat-card"><div class="stat-num">DeepSeek</div><div class="stat-label">AI 模型</div></div>' +
        '</div>' +
        '<div class="stats-section"><h4>知识分类分布</h4>' + catRows + '</div>' +
        '<p style="font-size:11px;color:var(--text-tertiary);margin-top:12px;">统计基于当前加载文档，不含已删除文件</p>';

    statsOverlay.style.display = "flex";
}

// ===== Export Chat =====
function exportChat() {
    const messages = chatMessages.querySelectorAll(".message");
    if (messages.length === 0) return;

    let md = "# 农业知识库 · 对话记录\n\n";
    md += "导出时间: " + new Date().toLocaleString("zh-CN") + "\n\n---\n\n";

    messages.forEach(msg => {
        const timeEl = msg.querySelector(".msg-time");
        const contentEl = msg.querySelector(".msg-content");
        const sourcesEl = msg.querySelector(".msg-sources");
        if (!contentEl) return;
        const time = timeEl ? timeEl.textContent : "";
        const text = contentEl.textContent.trim();
        if (!text) return;

        if (msg.classList.contains("user")) {
            md += "### 🙋 提问 (" + time + ")\n\n" + text + "\n\n";
        } else if (msg.classList.contains("assistant")) {
            md += "### 🤖 回答 (" + time + ")\n\n" + text + "\n\n";
            if (sourcesEl && sourcesEl.textContent.trim()) {
                md += "*参考来源: " + sourcesEl.textContent.trim() + "*\n\n";
            }
            md += "---\n\n";
        }
    });

    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "对话记录_" + new Date().toISOString().slice(0, 10) + ".md";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ===== File Upload =====
async function handleFileUpload(e) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setStatus("上传中...");
    let success = 0, fail = 0;
    for (const file of files) {
        const formData = new FormData();
        formData.append("file", file);
        try {
            const r = await fetch("/api/upload", { method: "POST", body: formData });
            const d = await r.json();
            if (r.ok && d.status === "ok") {
                success++;
            } else {
                fail++;
                addSystemMsg("❌ 上传「" + escHtml(file.name) + "」失败: " + (d.detail || d.error || "未知错误"));
            }
        } catch (err) {
            fail++;
            addSystemMsg("❌ 上传「" + escHtml(file.name) + "」失败: " + escHtml(err.message));
        }
    }
    if (success > 0) addSystemMsg("✅ 成功上传 " + success + " 个文档" + (fail > 0 ? "，" + fail + " 个失败" : ""));
    setStatus("就绪");
    fileUpload.value = "";
    loadKnowledgeBase();
}

// ===== UI Builders =====

function buildWelcomeHTML() {
    return '<div class="message system welcome-msg">' +
        '<div class="msg-content">' +
        '<p>👋 农业知识库 v4 · 20 篇专业文档 · BM25 语义检索</p>' +
        '<div class="suggestions" id="suggestions">' +
        buildSuggestionHTML() +
        '</div></div></div>';
}

function reattachSuggestions() {
    const sug = document.getElementById("suggestions");
    if (!sug) return;
    sug.addEventListener("click", (e) => {
        const card = e.target.closest(".sug-card");
        if (!card) return;
        const q = card.getAttribute("data-q");
        if (q) {
            userInput.value = q;
            sendMessage();
        }
    });
}

function addUserMsg(t) {
    const time = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    const d = document.createElement("div");
    d.className = "message user";
    d.innerHTML = '<div class="msg-content">' + escHtml(t) + '<div class="msg-time">' + time + '</div></div>';
    chatMessages.appendChild(d);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addAssistantMsg() {
    const time = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    const d = document.createElement("div");
    d.className = "message assistant";
    d.setAttribute("data-time", time);
    d.innerHTML = '<div class="msg-content"></div>' +
        '<div class="msg-sources"></div>' +
        '<div class="like-btns">' +
        '<button class="btn-like" title="有帮助">👍 <span class="like-count">0</span></button>' +
        '<button class="btn-dislike" title="无帮助">👎 <span class="dislike-count">0</span></button>' +
        '</div>' +
        '<button class="copy-btn" style="display:none" title="复制">📋</button>' +
        '<div class="msg-time">' + time + '</div>';

    // Like/Dislike handlers
    const likeBtn = d.querySelector(".btn-like");
    const dislikeBtn = d.querySelector(".btn-dislike");
    const likeCount = d.querySelector(".like-count");
    const dislikeCount = d.querySelector(".dislike-count");

    function rate(rating) {
        const isDown = rating === "down";
        const btn = isDown ? dislikeBtn : likeBtn;
        const other = isDown ? likeBtn : dislikeBtn;
        if (btn.classList.contains(isDown ? "disliked" : "liked")) {
            btn.classList.remove(isDown ? "disliked" : "liked");
            btn.querySelector("span").textContent = "0";
            return;
        }
        btn.classList.add(isDown ? "disliked" : "liked");
        other.classList.remove(isDown ? "liked" : "disliked");
        btn.querySelector("span").textContent = "1";
        other.querySelector("span").textContent = "0";
        sendFeedback(d, rating);
    }

    likeBtn.addEventListener("click", () => rate("up"));
    dislikeBtn.addEventListener("click", () => rate("down"));

    chatMessages.appendChild(d);
    return d;
}

// 把评价送回后端。meta 由 sendMessage / restoreChatHistory 挂在元素上。
async function sendFeedback(div, rating) {
    const meta = div._feedback;
    if (!meta) return;
    try {
        const resp = await fetch("/api/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                question: meta.question || "",
                answer: meta.answer || "",
                sources: meta.sources || [],
                rating: rating,
                session_id: sessionId
            })
        });
        const data = await resp.json();
        if (data.status === "ok") {
            div.querySelector(".like-btns").classList.add("sent");
        }
    } catch (_) {
        // 反馈失败不影响阅读，静默处理
    }
}

function addSystemMsg(t) {
    const d = document.createElement("div");
    d.className = "message system";
    d.innerHTML = '<div class="msg-content">' + t + "</div>";
    chatMessages.appendChild(d);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function setStatus(t) {
    statusEl.textContent = t;
    statusEl.style.background = t === "就绪" ? "#e8f5e9" : "#fff3e0";
}

async function copyText(text, btn) {
    try {
        await navigator.clipboard.writeText(text);
        btn.textContent = "✅";
        setTimeout(() => { btn.textContent = "📋"; }, 1500);
    } catch (e) {
        btn.textContent = "❌";
        setTimeout(() => { btn.textContent = "📋"; }, 1500);
    }
}

// ===== Markdown 渲染 =====
// 默认使用内置渲染器，不依赖任何 CDN：内网/断网环境也不会卡住页面。
// 如果页面额外引入了 marked，则优先用它。
function renderMarkdown(text) {
    if (typeof marked !== "undefined" && marked && typeof marked.parse === "function") {
        marked.setOptions({ breaks: true, gfm: true });
        return marked.parse(text);
    }
    return miniMarkdown(text);
}

// 覆盖模型实际会输出的语法子集：标题、加粗、行内代码、代码块、
// 有序/无序列表、表格、引用、分隔线、链接。
// 先做 HTML 转义再套标签，避免把模型输出当成 HTML 执行。
function miniMarkdown(src) {
    const lines = escHtml(String(src == null ? "" : src)).split("\n");
    const out = [];
    let i = 0;

    function inline(s) {
        return s
            .replace(/`([^`]+)`/g, "<code>$1</code>")
            .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
            .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>")
            .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)"'<>]+)\)/g,
                     '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    }

    function cells(line) {
        return line.trim().replace(/^\|/, "").replace(/\|$/, "")
                   .split("|").map(c => c.trim());
    }

    while (i < lines.length) {
        const line = lines[i];

        if (!line.trim()) { i++; continue; }

        // 代码块
        if (/^\s*```/.test(line)) {
            const buf = [];
            i++;
            while (i < lines.length && !/^\s*```/.test(lines[i])) { buf.push(lines[i]); i++; }
            i++;
            out.push("<pre><code>" + buf.join("\n") + "</code></pre>");
            continue;
        }

        // 表格：表头行 + 分隔行
        if (/^\s*\|/.test(line) && i + 1 < lines.length &&
            /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
            const head = cells(line);
            i += 2;
            const rows = [];
            while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(cells(lines[i])); i++; }
            out.push("<table><thead><tr>" +
                head.map(c => "<th>" + inline(c) + "</th>").join("") +
                "</tr></thead><tbody>" +
                rows.map(r => "<tr>" + r.map(c => "<td>" + inline(c) + "</td>").join("") + "</tr>").join("") +
                "</tbody></table>");
            continue;
        }

        // 标题
        const heading = line.match(/^\s*(#{1,6})\s+(.*)$/);
        if (heading) {
            const level = Math.min(heading[1].length, 6);
            out.push("<h" + level + ">" + inline(heading[2].trim()) + "</h" + level + ">");
            i++;
            continue;
        }

        // 分隔线
        if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { out.push("<hr>"); i++; continue; }

        // 引用（转义后 > 变成 &gt;）
        if (/^\s*&gt;\s?/.test(line)) {
            const buf = [];
            while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) {
                buf.push(lines[i].replace(/^\s*&gt;\s?/, ""));
                i++;
            }
            out.push("<blockquote>" + buf.map(inline).join("<br>") + "</blockquote>");
            continue;
        }

        // 有序列表
        if (/^\s*\d+[.)]\s+/.test(line)) {
            const items = [];
            while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
                items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
                i++;
            }
            out.push("<ol>" + items.map(t => "<li>" + inline(t) + "</li>").join("") + "</ol>");
            continue;
        }

        // 无序列表
        if (/^\s*[-*+]\s+/.test(line)) {
            const items = [];
            while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
                items.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
                i++;
            }
            out.push("<ul>" + items.map(t => "<li>" + inline(t) + "</li>").join("") + "</ul>");
            continue;
        }

        // 段落：至少吃掉一行，避免死循环
        const buf = [];
        while (i < lines.length && lines[i].trim()) {
            if (buf.length && /^\s*(#{1,6}\s|```|\||[-*+]\s|\d+[.)]\s|&gt;)/.test(lines[i])) break;
            buf.push(lines[i]);
            i++;
        }
        out.push("<p>" + buf.map(inline).join("<br>") + "</p>");
    }

    return out.join("");
}

function escHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
}

function escAttr(s) {
    return s.replace(/'/g, "&#39;").replace(/"/g, "&quot;");
}

// ===== Delegated click handlers for data-doc =====
chatMessages.addEventListener("click", (e) => {
    const srcLink = e.target.closest(".src-link");
    if (srcLink && srcLink.dataset.doc) {
        openDoc(srcLink.dataset.doc);
    }
});

kbList.addEventListener("click", (e) => {
    const item = e.target.closest(".kb-item");
    if (item && item.dataset.doc) {
        openDoc(item.dataset.doc);
        if (window.innerWidth <= 768) sidebar.classList.remove("open");
    }
});

// ===== Init =====
// 首次加载：用随机推荐替换 HTML 中的固定问题
(function() {
    var sug = document.getElementById("suggestions");
    if (sug) {
        sug.innerHTML = buildSuggestionHTML();
        // 重新绑定点击事件（因为 innerHTML 替换后原有事件失效）
        sug.addEventListener("click", function(e) {
            var card = e.target.closest(".sug-card");
            if (!card) return;
            var q = card.getAttribute("data-q");
            if (q) { userInput.value = q; sendMessage(); }
        });
    }
})();
// 页面加载时恢复之前的对话历史
restoreChatHistory();
loadKnowledgeBase();

// ===== 恢复对话历史 =====
async function restoreChatHistory() {
    try {
        var r = await fetch("/api/session/" + encodeURIComponent(sessionId));
        if (!r.ok) return;
        var data = await r.json();
        var msgs = data.messages || [];
        if (msgs.length === 0) return;
        // 移除欢迎消息
        var welcome = chatMessages.querySelector(".welcome-msg");
        if (welcome) welcome.remove();
        // 渲染历史消息
        var lastQuestion = "";
        msgs.forEach(function(m) {
            questionCount++;
            if (m.role === "user") {
                lastQuestion = m.content;
                addUserMsg(m.content);
            } else if (m.role === "assistant") {
                var div = addAssistantMsg();
                div.querySelector(".msg-content").innerHTML = renderMarkdown(m.content);
                var copyBtn = div.querySelector(".copy-btn");
                if (copyBtn) copyBtn.style.display = "block";
                if (copyBtn) copyBtn.onclick = function() { copyText(m.content, copyBtn); };
                div._feedback = { question: lastQuestion, answer: m.content, sources: [] };
            }
        });
        chatMessages.scrollTop = chatMessages.scrollHeight;
    } catch (_) {}
}
