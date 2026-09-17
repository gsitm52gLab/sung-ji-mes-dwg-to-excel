/* 채팅 화면 상태와 렌더.
 *
 * 대화 이력은 이 배열 하나에만 있다. 새로고침하면 사라진다 — 서버는 무상태다.
 * 서버와의 계약은 SSE 프레임 세 가지(token / done / error)뿐이다.
 */

const $ = (id) => document.getElementById(id);

const loginScreen = $("login-screen");
const appScreen = $("app-screen");
const chatEl = $("chat");
const inputEl = $("input");
const sendBtn = $("send");

/** @type {{role: 'user'|'assistant', content: string}[]} */
const history = [];
let busy = false;

/* ── 렌더 헬퍼 ───────────────────────────────────────── */

function atBottom() {
  // 사용자가 위로 올려 읽는 중이라면 스크롤을 뺏지 않는다.
  return chatEl.scrollHeight - chatEl.scrollTop - chatEl.clientHeight < 80;
}

function scrollDown() {
  chatEl.scrollTop = chatEl.scrollHeight;
}

function notice(text, kind) {
  const el = document.createElement("div");
  el.className = "sys-notice" + (kind === "warn" ? " warn" : "");
  const icon = document.createElement("i");
  icon.className = kind === "warn" ? "ti ti-alert-triangle" : "ti ti-circle-check";
  el.append(icon, document.createTextNode(text));
  chatEl.appendChild(el);
  scrollDown();
}

function userBubble(text) {
  const el = document.createElement("div");
  el.className = "bubble-user";
  const p = document.createElement("p");
  p.textContent = text;
  el.appendChild(p);
  chatEl.appendChild(el);
  scrollDown();
}

function aiBubble() {
  const el = document.createElement("div");
  el.className = "bubble-ai";
  el.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
  chatEl.appendChild(el);
  scrollDown();
  return el;
}

// 모델 출력은 마크다운이다. 표를 자주 쓰므로 그대로 두면 읽기 어렵다.
// 렌더 전에 반드시 DOMPurify 를 통과시킨다.
function renderMarkdown(el, text) {
  el.innerHTML = DOMPurify.sanitize(marked.parse(text, { breaks: true }));
}

function errorCard(message, onRetry) {
  const el = document.createElement("div");
  el.className = "error-card";
  const p = document.createElement("div");
  p.textContent = message;
  el.appendChild(p);
  if (onRetry) {
    const btn = document.createElement("button");
    btn.className = "retry";
    btn.textContent = "다시 시도";
    btn.onclick = () => { el.remove(); onRetry(); };
    el.appendChild(btn);
  }
  chatEl.appendChild(el);
  scrollDown();
}

/* ── 첫 화면 ─────────────────────────────────────────── */

function renderZones(data) {
  const list = $("zonelist");
  list.innerHTML = "";
  (data.zones || []).forEach((name) => {
    const el = document.createElement("div");
    el.className = "zone";
    const i = document.createElement("i");
    i.className = "ti ti-circle-check";
    const span = document.createElement("span");
    span.textContent = name;
    el.append(i, span);
    list.appendChild(el);
  });
}

function renderSummary(data) {
  if (!data.available) {
    notice("대조 결과가 없습니다 — 파이프라인을 먼저 실행한 뒤 스냅샷을 갱신하세요.", "warn");
    return;
  }
  renderZones(data);
  notice(`대조 결과 로드됨 · ${data.zones.length}개 구역 · 비교 셀 ${data.cell_count}건`);

  const card = document.createElement("div");
  card.className = "result-card";
  const loc = document.createElement("div");
  loc.className = "loc";
  loc.textContent = data.zones.join(" · ");
  const badges = document.createElement("div");
  badges.className = "badges";
  const spec = [
    ["pass", `일치 ${data.match_count}`],
    ["warn", `비교불가 ${data.na_count}`],
    ["err", `불일치 ${data.bad_count}`],
  ];
  spec.forEach(([cls, text]) => {
    const b = document.createElement("span");
    b.className = "badge " + cls;
    b.textContent = text;
    badges.appendChild(b);
  });
  card.append(loc, badges);
  chatEl.appendChild(card);

  if (data.bad_count === 0) {
    notice("어긋난 셀이 없습니다. 비교한 모든 셀이 도면과 엑셀에서 일치했습니다.");
  } else {
    notice(`어긋난 셀 ${data.bad_count}건이 있습니다. "불일치 보여줘" 라고 물어보세요.`, "warn");
  }
}

/* ── 대화 ────────────────────────────────────────────── */

function setBusy(value) {
  busy = value;
  sendBtn.disabled = value;
  inputEl.disabled = value;
  if (!value) inputEl.focus();
}

/** 서버에서 받은 SSE 바이트 스트림을 프레임 단위로 넘겨준다. */
async function* readSSE(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // 프레임 구분자는 빈 줄이다. 마지막 조각은 다음 청크와 이어붙인다.
    const frames = buffer.split("\n\n");
    buffer = frames.pop();
    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) yield { event, data: JSON.parse(data) };
    }
  }
}

async function send(text) {
  history.push({ role: "user", content: text });
  userBubble(text);
  setBusy(true);

  const bubble = aiBubble();
  let acc = "";

  const retry = () => {
    // 실패한 차례의 사용자 발화는 이력에 남아 있다. 그대로 다시 보낸다.
    bubble.remove();
    const last = history[history.length - 1];
    if (last && last.role === "user") {
      history.pop();
      send(last.content);
    }
  };

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });

    if (response.status === 401) {
      bubble.remove();
      showLogin("세션이 만료됐습니다. 다시 로그인해 주세요.");
      setBusy(false);
      return;
    }
    if (!response.ok) {
      bubble.remove();
      errorCard(`서버 오류 ${response.status}`, retry);
      setBusy(false);
      return;
    }

    let failed = false;
    for await (const { event, data } of readSSE(response)) {
      if (event === "token") {
        acc += data.text;
        const stick = atBottom();
        renderMarkdown(bubble, acc);
        if (stick) scrollDown();
      } else if (event === "error") {
        failed = true;
        // 부분 응답은 남긴다. 어디까지 받았는지가 재시도 판단에 쓸모 있다.
        if (!acc) bubble.remove();
        errorCard(data.message, retry);
      }
    }

    if (!failed && acc) {
      history.push({ role: "assistant", content: acc });
    } else if (!failed && !acc) {
      bubble.remove();
      errorCard("응답이 비어 있습니다.", retry);
    }
  } catch (err) {
    // 네트워크가 끊기거나 스트리밍 중 연결이 죽은 경우.
    if (!acc) bubble.remove();
    errorCard(`연결이 끊겼습니다: ${err.message}`, retry);
  } finally {
    setBusy(false);
  }
}

/* ── 입력 ────────────────────────────────────────────── */

function autoGrow() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
}

function submitInput(event) {
  if (event) event.preventDefault();
  const text = inputEl.value.trim();
  if (!text || busy) return;
  inputEl.value = "";
  autoGrow();
  send(text);
}

inputEl.addEventListener("input", autoGrow);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    submitInput();
  }
});
$("chat-form").addEventListener("submit", submitInput);

/* ── 도면 업로드 ─────────────────────────────────────── */

// 서버가 SSE 로 알려 주는 단계들. 화면 순서는 여기 적힌 순서를 따른다.
const STEPS = [
  ["upload", "도면 접수"],
  ["convert", "dwg → dxf 변환"],
  ["compare", "일람표 대조"],
  ["done", "완료"],
];

function showProgress(activeStep) {
  const block = $("progress-block");
  const hr = $("progress-hr");
  block.hidden = false;
  hr.hidden = false;

  const activeIndex = STEPS.findIndex(([key]) => key === activeStep);
  const steps = $("steps");
  steps.innerHTML = "";
  STEPS.forEach(([key, label], i) => {
    const state = i < activeIndex ? "done" : i === activeIndex ? "current" : "todo";
    const el = document.createElement("div");
    el.className = "step " + state;
    const icon = document.createElement("i");
    icon.className =
      state === "done" ? "ti ti-circle-check"
      : state === "current" ? "ti ti-loader-2"
      : "ti ti-circle-dashed";
    const span = document.createElement("span");
    span.textContent = label;
    el.append(icon, span);
    steps.appendChild(el);
  });
}

function hideProgress() {
  $("progress-block").hidden = true;
  $("progress-hr").hidden = true;
}

function uploadNote(text, isError) {
  const el = $("upload-note");
  el.textContent = text || "";
  el.classList.toggle("err", Boolean(isError));
}

async function uploadDwg(file) {
  if (busy) return;
  setBusy(true);
  $("pick-file").disabled = true;
  uploadNote("");
  showProgress("upload");
  notice(`도면 업로드: ${file.name}`);

  const body = new FormData();
  body.append("file", file);

  try {
    const response = await fetch("/api/upload", { method: "POST", body });
    if (response.status === 401) { showLogin("세션이 만료됐습니다."); return; }
    if (!response.ok) {
      let detail = `서버 오류 ${response.status}`;
      try { detail = (await response.json()).detail || detail; } catch (e) { /* 본문 없음 */ }
      throw new Error(detail);
    }

    let failed = false;
    for await (const { event, data } of readSSE(response)) {
      if (event === "progress") {
        showProgress(data.step);
      } else if (event === "complete") {
        // 대조 결과가 통째로 바뀌었다. 화면도 새 결과로 다시 그린다.
        renderZones(data.data);
        notice(`대조 완료 · ${data.data.zones.length}개 구역 · 비교 셀 ${data.data.cell_count}건`);
        if (data.data.bad_count === 0) {
          notice("어긋난 셀이 없습니다. 비교한 모든 셀이 일치했습니다.");
        } else {
          notice(`어긋난 셀 ${data.data.bad_count}건이 있습니다.`, "warn");
        }
        uploadNote(`${file.name} 반영됨`);
        // 상단 파일명도 방금 올린 도면으로 바꾼다. 그대로 두면 화면이
        // 옛 도면을 가리키면서 새 대조 결과를 보여주는 꼴이 된다.
        $("detail-name").textContent = file.name;
      } else if (event === "error") {
        failed = true;
        errorCard(data.message);
        uploadNote("처리하지 못했습니다", true);
      }
    }
    if (failed) hideProgress();
    else setTimeout(hideProgress, 1500);
  } catch (err) {
    errorCard(`업로드 실패: ${err.message}`);
    uploadNote(err.message, true);
    hideProgress();
  } finally {
    $("pick-file").disabled = false;
    setBusy(false);
    $("dwg-file").value = "";
  }
}

$("pick-file").addEventListener("click", () => $("dwg-file").click());
$("dwg-file").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (file) uploadDwg(file);
});

// 끌어다 놓기도 받는다. 파일 선택 대화상자보다 이쪽이 빠르다.
const dropTarget = $("pick-file");
["dragenter", "dragover"].forEach((type) =>
  dropTarget.addEventListener(type, (e) => {
    e.preventDefault();
    dropTarget.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((type) =>
  dropTarget.addEventListener(type, (e) => {
    e.preventDefault();
    dropTarget.classList.remove("dragover");
  })
);
dropTarget.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".dwg")) {
    uploadNote("dwg 파일만 올릴 수 있습니다", true);
    return;
  }
  uploadDwg(file);
});

/* ── 인증 ────────────────────────────────────────────── */

function showLogin(message) {
  appScreen.hidden = true;
  loginScreen.hidden = false;
  $("login-error").textContent = message || "";
  $("password").focus();
}

function showApp(meta) {
  loginScreen.hidden = true;
  appScreen.hidden = false;
  $("model-name").textContent = meta.provider ? `${meta.model} · ${meta.provider}` : meta.model;
  chatEl.innerHTML = "";
  hideProgress();
  renderSummary(meta.data);
  // 변환기가 없는 환경(로컬 맥 등)에서는 업로드를 눌러도 실패한다.
  // 눌리기 전에 그 사실을 알린다.
  if (!meta.upload_enabled) {
    $("pick-file").disabled = true;
    uploadNote("이 서버에는 도면 변환기가 없어 업로드를 쓸 수 없습니다. 배포 환경에서만 동작합니다.");
  }
  inputEl.focus();
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("login-submit");
  btn.disabled = true;
  $("login-error").textContent = "";
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: $("password").value }),
    });
    if (!res.ok) {
      $("login-error").textContent = "비밀번호가 맞지 않습니다.";
      return;
    }
    $("password").value = "";
    await boot();
  } catch (err) {
    $("login-error").textContent = `접속할 수 없습니다: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
});

async function boot() {
  try {
    const meta = await (await fetch("/api/meta")).json();
    if (meta.authed) showApp(meta);
    else showLogin();
  } catch (err) {
    showLogin(`서버에 연결할 수 없습니다: ${err.message}`);
  }
}

boot();
