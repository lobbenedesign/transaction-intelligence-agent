const STORAGE_KEY = "txnagent.onboarding.dismissed.v1";
const THEME_KEY = "txnagent.theme";

const SUGGESTED_QUERIES = [
  "quanto spendo in abbonamenti ogni mese?",
  "quali abbonamenti sono aumentati di prezzo?",
  "ho abbonamenti sovrapposti?",
];

let sessionId = null;

function initOnboarding() {
  const backdrop = document.getElementById("onboarding-backdrop");
  const dismissBtn = document.getElementById("onboarding-dismiss");
  let dismissed = false;
  try {
    dismissed = !!window.localStorage.getItem(STORAGE_KEY);
  } catch {
    dismissed = false;
  }
  if (!dismissed) backdrop.hidden = false;

  dismissBtn.addEventListener("click", () => {
    backdrop.hidden = true;
    try {
      window.localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      // ignore
    }
  });
}

function initTheme() {
  let theme = "dark";
  try {
    theme = window.localStorage.getItem(THEME_KEY) || "dark";
  } catch {
    // ignore
  }
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("theme-toggle");
  btn.textContent = theme === "dark" ? "☀︎" : "☾";
  btn.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    btn.textContent = next === "dark" ? "☀︎" : "☾";
    try {
      window.localStorage.setItem(THEME_KEY, next);
    } catch {
      // ignore
    }
  });
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${url} failed: ${res.status}`);
  return res.json();
}

async function loadHealth() {
  const health = await fetchJson("/healthz");
  const strip = document.getElementById("stat-strip");
  strip.innerHTML = "";
  const div = document.createElement("div");
  div.className = "stat-item";
  div.innerHTML = `<span class="stat-value">${health.transactions_loaded}</span><span class="stat-label">transazioni caricate</span>`;
  strip.appendChild(div);
}

function initSuggestions() {
  const container = document.getElementById("suggestions");
  container.innerHTML = SUGGESTED_QUERIES.map((q) => `<button type="button" class="suggestion-chip">${q}</button>`).join("");
  container.querySelectorAll(".suggestion-chip").forEach((btn, i) => {
    btn.addEventListener("click", () => {
      document.getElementById("query-input").value = SUGGESTED_QUERIES[i];
      document.getElementById("ask-form").requestSubmit();
    });
  });
}

function appendChatTurn(question, answer, trace) {
  const log = document.getElementById("chat-log");
  const empty = log.querySelector(".chat-empty");
  if (empty) empty.remove();

  const turn = document.createElement("div");
  turn.className = "chat-turn";

  const q = document.createElement("div");
  q.className = "chat-question";
  q.textContent = question;
  turn.appendChild(q);

  const a = document.createElement("div");
  a.className = "chat-answer";
  a.innerHTML = `<div>${answer}</div>`;

  if (trace && trace.length) {
    const traceId = `trace-${Date.now()}`;
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "trace-toggle";
    toggle.textContent = `mostra i ${trace.length} passaggi`;
    const list = document.createElement("div");
    list.className = "trace-list";
    list.id = traceId;
    list.hidden = true;
    list.innerHTML = trace
      .map((t) => `<div class="trace-step"><span class="trace-kind">${t.kind}</span> — ${JSON.stringify(t.payload)}</div>`)
      .join("");
    toggle.addEventListener("click", () => {
      list.hidden = !list.hidden;
      toggle.textContent = list.hidden ? `mostra i ${trace.length} passaggi` : "nascondi i passaggi";
    });
    a.appendChild(toggle);
    a.appendChild(list);
  }

  turn.appendChild(a);
  log.appendChild(turn);
  log.scrollTop = log.scrollHeight;
}

async function submitAsk(event) {
  event.preventDefault();
  const input = document.getElementById("query-input");
  const query = input.value.trim();
  if (!query) return;
  input.value = "";

  try {
    const result = await fetchJson("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, session_id: sessionId }),
    });
    sessionId = result.session_id;
    appendChatTurn(query, result.answer, result.trace);
  } catch (err) {
    appendChatTurn(query, `Errore: ${err.message}`, []);
  }
}

async function loadRecurring() {
  const data = await fetchJson("/recurring");
  const list = document.getElementById("recurring-list");
  if (!data.series.length) {
    list.innerHTML = '<li class="insight-empty">Nessuna serie ricorrente rilevata.</li>';
    return;
  }
  list.innerHTML = data.series
    .map(
      (s) => `
      <li>
        <div class="insight-head">
          <span class="insight-name">${s.display_name}<span class="status-badge ${s.status}">${s.status.replace("_", " ")}</span></span>
          <span class="insight-value">${s.monthly_equivalent.toFixed(2)}€/mese</span>
        </div>
      </li>
    `
    )
    .join("");
}

async function loadPriceIncreases() {
  const data = await fetchJson("/price-increases");
  const list = document.getElementById("price-list");
  if (!data.series.length) {
    list.innerHTML = '<li class="insight-empty">Nessun aumento di prezzo rilevato.</li>';
    return;
  }
  list.innerHTML = data.series
    .map(
      (s) => `
      <li>
        <div class="insight-head">
          <span class="insight-name">${s.display_name}</span>
          <span class="price-up">+${(s.price_change_pct * 100).toFixed(1)}%</span>
        </div>
        <div class="insight-empty">${s.first_amount.toFixed(2)}€ → ${s.last_amount.toFixed(2)}€</div>
      </li>
    `
    )
    .join("");
}

async function loadOverlaps() {
  const data = await fetchJson("/subscription-overlaps");
  const list = document.getElementById("overlap-list");
  if (!data.overlaps.length) {
    list.innerHTML = '<li class="insight-empty">Nessuna sovrapposizione rilevata.</li>';
    return;
  }
  list.innerHTML = data.overlaps
    .map(
      (o) => `
      <li>
        <div class="insight-head">
          <span class="insight-name">${o.category}</span>
          <span class="insight-value">${o.total_monthly_cost.toFixed(2)}€/mese</span>
        </div>
        <div class="insight-empty">${o.merchants.join(", ")}</div>
      </li>
    `
    )
    .join("");
}

async function main() {
  initOnboarding();
  initTheme();
  initSuggestions();
  document.getElementById("chat-log").innerHTML = '<p class="chat-empty">Fai una domanda per iniziare, o usa un suggerimento qui sotto.</p>';
  document.getElementById("ask-form").addEventListener("submit", submitAsk);
  await Promise.all([loadHealth(), loadRecurring(), loadPriceIncreases(), loadOverlaps()]);
}

main();
