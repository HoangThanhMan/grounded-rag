/* grounded-rag demo UI. Talks to the same origin that serves it.

   One idea runs through the whole page: the gradient is the entailment scale.
   The band in the hero is the legend; every gauge below it is the same scale at
   row size, so a claim that only just cleared τ looks different from one that
   sailed over it. */

const $ = (sel) => document.querySelector(sel);

const form = $("#ask-form");
const questionEl = $("#question");
const submitEl = $("#submit");
const configEl = $("#config");
const asOfEl = $("#as-of");
const resultEl = $("#result");
const healthEl = $("#health");
const scaleEl = $("#scale");
const scaleTauEl = $("#scale-tau");
const scaleTauLabelEl = $("#scale-tau-label");
const scaleNoteEl = $("#scale-note");

// Filled from GET /configs; the fallback keeps the page usable if that 404s.
let CONFIGS = { full: { guard_enabled: true, entailment_threshold: 0.5 } };

const STATUS = {
  answered: "Đã trả lời",
  partial: "Trả lời một phần",
  abstained: "Từ chối trả lời",
  no_context: "Không có căn cứ trong tài liệu",
};

const VERDICT = {
  supported: "có căn cứ",
  unsupported: "không đủ căn cứ",
  uncited: "không trích dẫn",
  null: "không kiểm chứng",
};

// The four layers of defence, cheapest first — the order they actually run in.
const LAYERS = [
  ["retrieval_floor", "Ngưỡng truy xuất", "Không đoạn nào đủ liên quan, LLM không được gọi"],
  ["out_of_domain", "Phạm vi câu hỏi", "Bộ lập kế hoạch thấy đây không phải câu hỏi pháp luật"],
  ["model", "Model tự từ chối", "Model dùng đúng câu từ chối mà prompt cho sẵn"],
  ["guard", "Guard NLI", "Không mệnh đề nào được đoạn nó trích chứng minh"],
];

const STEP_NAME = {
  retrieve: "Truy xuất",
  plan: "Lập kế hoạch",
  generate: "Sinh câu trả lời",
  verify: "Kiểm chứng",
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

const seconds = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1).replace(".", ",")} giây` : `${ms} ms`);

// Vietnamese writes the decimal separator as a comma, including on scores.
const num2 = (x) => x.toFixed(2).replace(".", ",");

const tauOf = (name) => CONFIGS[name]?.entailment_threshold ?? 0.5;
const guardOf = (name) => CONFIGS[name]?.guard_enabled ?? true;

/* -------------------------------------------------------------- startup -- */

function autoGrow() {
  questionEl.style.height = "auto";
  questionEl.style.height = `${questionEl.scrollHeight}px`;
}
questionEl.addEventListener("input", autoGrow);

questionEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

$("#samples").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  questionEl.value = btn.textContent;
  autoGrow();
  form.requestSubmit();
});

/* The hero band is the legend for every gauge on the page, so it has to show
   the threshold the selected configuration actually runs at. */
function paintScale() {
  const name = configEl.value || "full";
  const tau = tauOf(name);
  const on = guardOf(name);

  scaleEl.classList.toggle("guard-off", !on);
  scaleTauEl.style.left = `${(tau * 100).toFixed(1)}%`;
  scaleTauLabelEl.textContent = `τ ${num2(tau)}`;
  scaleNoteEl.textContent = on
    ? `Mệnh đề dưới vạch τ bị loại khỏi câu trả lời. Cấu hình “${name}” chấm ở ${num2(tau)}.`
    : `Cấu hình “${name}” tắt guard: mệnh đề được liệt kê nhưng không mệnh đề nào bị chặn.`;
}
configEl.addEventListener("change", paintScale);

async function boot() {
  try {
    const health = await (await fetch("/healthz")).json();
    healthEl.textContent = `provider ${health.provider}`;
    healthEl.hidden = false;
  } catch {
    healthEl.textContent = "API không phản hồi";
    healthEl.classList.add("down");
    healthEl.hidden = false;
  }

  let names = ["full", "agentic", "threshold", "baseline"];
  try {
    const list = await (await fetch("/configs")).json();
    CONFIGS = Object.fromEntries(list.map((c) => [c.name, c]));
    names = list.map((c) => c.name);
  } catch {
    /* keep the fallback list */
  }
  configEl.innerHTML = names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  if (names.includes("full")) configEl.value = "full";

  // ?q=...&config=... asks straight away, so a demo run is a shareable link.
  const params = new URLSearchParams(location.search);
  if (params.get("config") && names.includes(params.get("config"))) configEl.value = params.get("config");
  if (params.get("as_of")) asOfEl.value = params.get("as_of");

  paintScale();

  if (params.get("q")) {
    questionEl.value = params.get("q");
    autoGrow();
    form.requestSubmit();
  }
}
boot();

/* ------------------------------------------------------------------ ask -- */

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = questionEl.value.trim();
  if (!question) return;

  const config = configEl.value || "full";
  const payload = { question, config };
  if (asOfEl.value) payload.as_of = asOfEl.value;

  document.body.classList.add("answering");
  document.body.classList.remove("answered");
  submitEl.disabled = true;
  submitEl.textContent = "Đang hỏi";
  resultEl.hidden = false;
  resultEl.innerHTML = `<div class="waiting">
    <div class="waiting-band"></div>
    <p>Đang <em>truy xuất</em>, rồi <em>sinh câu trả lời</em>, rồi <em>kiểm chứng</em> từng
       mệnh đề. Trên CPU bước xếp hạng lại thường mất 5–15 giây.</p>
  </div>`;

  const started = performance.now();
  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!res.ok) {
      renderFailure(res.status, body.detail ?? JSON.stringify(body));
      return;
    }
    render(body, config);
  } catch (err) {
    renderFailure(0, `Không kết nối được tới API sau ${seconds(Math.round(performance.now() - started))}. ${err}`);
  } finally {
    document.body.classList.remove("answering");
    document.body.classList.add("answered");
    submitEl.disabled = false;
    submitEl.textContent = "Hỏi";
  }
});

function renderFailure(status, detail) {
  const hint =
    status === 404
      ? "Cấu hình này không có trong thư mục configs/."
      : status === 503
        ? "Provider LLM không phản hồi. Kiểm tra LLM_PROVIDER và khoá API trong .env."
        : "Kiểm tra API đang chạy: make run.";
  resultEl.innerHTML = `<div class="failed">
    <h2>Không lấy được câu trả lời</h2>
    <p>${esc(hint)}</p>
    <p><code>${esc(detail)}</code></p>
  </div>`;
}

/* --------------------------------------------------------------- render -- */

function render(res, configName) {
  const tau = tauOf(configName);
  const guardOn = guardOf(configName);
  const meta = res.meta ?? {};
  const claims = res.claims ?? [];
  const sources = res.sources ?? [];

  const abstained = res.status === "abstained" || res.status === "no_context";

  resultEl.innerHTML = `
    <div class="collation">
      <div class="sheet">
        ${verdictLine(res, meta)}
        <p class="answer">${withCitations(res.answer)}</p>
        ${claims.length ? ledger(claims, tau, guardOn) : ""}
        ${abstained ? layers(meta.abstain_reason) : ""}
      </div>
      ${tray(sources)}
      ${pipeline(meta)}
    </div>`;

  wire();
}

function verdictLine(res, meta) {
  const bits = [];
  if (meta.latency_ms) bits.push(seconds(meta.latency_ms));
  if (meta.llm_calls != null) bits.push(`${meta.llm_calls} lượt gọi LLM`);
  if (meta.tokens) bits.push(`${meta.tokens} token`);
  if (meta.regenerated) bits.push("đã sinh lại một lần");

  const dropped = (res.claims ?? []).filter((c) => c.verdict && c.verdict !== "supported");
  const note = dropped.length
    ? `<p class="dropped">Guard đã loại ${dropped.length} mệnh đề khỏi câu trả lời trên. Chúng vẫn nằm trong bảng
       dưới đây, gạch ngang, kèm điểm của chúng.</p>`
    : "";

  return `<div class="verdict-line">
    <span class="status" data-status="${esc(res.status)}">${esc(STATUS[res.status] ?? res.status)}</span>
    <span class="cost">${bits.map((b) => `<span>${esc(b)}</span>`).join("")}</span>
    ${note}
  </div>`;
}

function withCitations(text) {
  return esc(text).replace(/\[(C\d+)\]/g, (_, label) => `<button class="cite" data-label="${label}">${label}</button>`);
}

function ledger(claims, tau, guardOn) {
  const note = guardOn
    ? `Cùng thang màu với dải ở trên; vạch đen là τ ${num2(tau)}.`
    : "Cấu hình này tắt guard: mệnh đề được liệt kê nhưng không được kiểm chứng.";

  return `<section class="ledger">
    <div class="ledger-head">
      <h2>Từng mệnh đề, đối chiếu với đoạn nó trích</h2>
      <p>${esc(note)}</p>
    </div>
    ${claims.map((c) => claimRow(c, tau)).join("")}
  </section>`;
}

function claimRow(claim, tau) {
  const verdict = claim.verdict ?? "null";
  const score = claim.entailment;
  const cites = (claim.citations ?? []).join(",");

  // The fill scales the gradient so it still spans the whole track: the colour
  // a claim ends on is its position on the scale, not a verdict swatch.
  const pct = score == null ? 0 : Math.max(1, Math.min(100, score * 100));
  const fill = score == null ? "" : `<span class="fill" style="--pct:${pct.toFixed(1)}"></span>`;

  return `<button type="button" class="claim" data-verdict="${esc(verdict)}"
      data-cites="${esc(cites)}" aria-pressed="false">
    <p class="claim-text">${esc(claim.text)}</p>
    <div class="claim-foot">
      <span class="tag">${esc(VERDICT[verdict] ?? verdict)}</span>
      ${(claim.citations ?? []).map((l) => `<span class="cite">${esc(l)}</span>`).join("")}
      ${claim.cited_as ? `<span class="recited">model trích ${esc(claim.cited_as.join(", "))}</span>` : ""}
      <span class="gauge">
        <span class="track">
          ${fill}
          <span class="tau" style="left:${(tau * 100).toFixed(1)}%"></span>
        </span>
        <span class="score${score == null ? " none" : ""}">${score == null ? "—" : num2(score)}</span>
      </span>
    </div>
  </button>`;
}

function layers(reason) {
  return `<section class="layers">
    <h2>Bốn lớp phòng vệ</h2>
    <p>Xếp theo thứ tự chạy, rẻ trước. Lớp nào chặn được thì các lớp sau không phải chạy.</p>
    <ol>${LAYERS.map(
      ([key, name, what]) =>
        `<li class="${key === reason ? "fired" : ""}"><span>${esc(name)} — ${esc(what)}</span></li>`,
    ).join("")}</ol>
  </section>`;
}

function tray(sources) {
  if (!sources.length) {
    return `<aside class="tray-panel">
      <div class="tray-head"><h2>Căn cứ</h2></div>
      <p class="tray-note">Không đoạn nào vượt ngưỡng truy xuất, nên không có gì để đối chiếu.</p>
    </aside>`;
  }
  return `<aside class="tray-panel">
    <div class="tray-head">
      <h2>Căn cứ</h2>
      <button type="button" id="clear-filter" hidden>Xem tất cả</button>
    </div>
    <p class="tray-note">Bấm vào một mệnh đề để chỉ hiện đoạn luật nó được đối chiếu với.</p>
    ${sources.map(sourceCard).join("")}
  </aside>`;
}

function sourceCard(s) {
  const c = s.chunk ?? {};
  const where = [c.article, c.clause].filter(Boolean).join(", ") || c.ref || c.chunk_id;
  const doc = [c.doc_title ?? c.doc_id, c.chapter].filter(Boolean).join(" — ");
  const text = c.text ?? "";
  return `<article class="source" data-label="${esc(s.label)}">
    <div class="source-head">
      <span class="source-label">${esc(s.label)}</span>
      <span class="source-ref">${esc(where)}</span>
      <span class="source-score">${num2(Number(s.score))}</span>
    </div>
    ${doc ? `<p class="source-doc">${esc(doc)}</p>` : ""}
    <p class="source-text">${esc(text)}</p>
    ${text.length > 300 ? `<button type="button" class="more">Đọc cả đoạn</button>` : ""}
  </article>`;
}

function pipeline(meta) {
  const steps = meta.steps ?? [];
  if (!steps.length) return "";
  const total = steps.reduce((a, s) => a + (s.ms || 0), 0) || 1;

  // The pipeline can run a step twice (a retry, a corrective round). Number the
  // repeats so two identical labels are not two mysteries.
  const seen = {};
  const runs = steps.map((s) => (seen[s.name] = (seen[s.name] || 0) + 1));
  const label = (s, i) => {
    const base = STEP_NAME[s.name] ?? s.name;
    const times = steps.filter((x) => x.name === s.name).length;
    return times > 1 ? `${base} (lần ${runs[i]})` : base;
  };

  return `<section class="pipeline">
    <h2>Thời gian dùng ở đâu</h2>
    <div class="timeline">
      ${steps
        .map(
          (s, i) =>
            `<span class="span" data-name="${esc(s.name)}" style="flex:${Math.max(s.ms, 1)}"
               title="${esc(label(s, i))} ${s.ms} ms"></span>`,
        )
        .join("")}
    </div>
    <ul class="spans">
      ${steps
        .map(
          (s, i) =>
            `<li><span class="swatch" data-name="${esc(s.name)}"></span>
             ${esc(label(s, i))} <b>${seconds(s.ms)}</b></li>`,
        )
        .join("")}
      <li>Tổng <b>${seconds(total)}</b></li>
    </ul>
  </section>`;
}

/* --------------------------------------------------------- interactions -- */

function wire() {
  const collation = resultEl.querySelector(".collation");
  const clearBtn = resultEl.querySelector("#clear-filter");

  const clear = () => {
    collation.classList.remove("filtered");
    resultEl.querySelectorAll(".claim").forEach((c) => c.setAttribute("aria-pressed", "false"));
    resultEl.querySelectorAll(".source").forEach((s) => s.classList.remove("lit"));
    if (clearBtn) clearBtn.hidden = true;
  };

  const lit = (labels) => {
    collation.classList.add("filtered");
    resultEl.querySelectorAll(".source").forEach((s) => {
      s.classList.toggle("lit", labels.includes(s.dataset.label));
    });
    if (clearBtn) clearBtn.hidden = false;
  };

  resultEl.querySelectorAll(".claim").forEach((claim) => {
    claim.addEventListener("click", () => {
      const on = claim.getAttribute("aria-pressed") === "true";
      clear();
      if (on) return;
      claim.setAttribute("aria-pressed", "true");
      lit(claim.dataset.cites ? claim.dataset.cites.split(",") : []);
    });
  });

  // A [C1] inside the answer jumps to the passage it points at.
  resultEl.querySelectorAll("button.cite[data-label]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = resultEl.querySelector(`.source[data-label="${btn.dataset.label}"]`);
      if (!target) return;
      clear();
      lit([btn.dataset.label]);
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });

  resultEl.querySelectorAll(".more").forEach((btn) => {
    btn.addEventListener("click", () => {
      const p = btn.previousElementSibling;
      const open = p.classList.toggle("open");
      btn.textContent = open ? "Thu gọn" : "Đọc cả đoạn";
    });
  });

  if (clearBtn) clearBtn.addEventListener("click", clear);
}
