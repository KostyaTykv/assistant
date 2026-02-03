(function () {
  const panel = document.getElementById("panel");
  if (!panel) return;

  const surveyKey = panel.dataset.surveyKey;
  const startQid = panel.dataset.startQid;

  
  const qTitle = document.getElementById("qTitle");
  const qText = document.getElementById("qText");
  const qLong = document.getElementById("qLong");

  const hintBox = document.getElementById("hintBox");
  const qHints = document.getElementById("qHints");

  const form = document.getElementById("form");
  const inputs = document.getElementById("inputs");
  const nextBtn = document.getElementById("nextBtn");
  const restartBtn = document.getElementById("restartBtn");

  const resultBox = document.getElementById("resultBox");
  const finalTitle = document.getElementById("finalTitle");
  const finalText = document.getElementById("finalText");
  const copyBtn = document.getElementById("copyBtn");
  const qCard = document.getElementById("qCard");

  let current = null;
  let answers = [];

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  async function fetchQuestion(qid) {
    const res = await fetch(`/api/s/${encodeURIComponent(surveyKey)}/q/${encodeURIComponent(qid)}`);
    if (!res.ok) throw new Error("question_load_failed");
    return await res.json();
  }

  function setEnabledByState() {
    if (!current) { nextBtn.disabled = true; return; }

    const t = current.type;
    if (t === "single") {
      const checked = inputs.querySelector('input[type="radio"][name="single"]:checked');
      nextBtn.disabled = !checked;
      return;
    }
    if (t === "multi") {
      const checked = inputs.querySelectorAll('input[type="checkbox"][name="multi"]:checked');
      nextBtn.disabled = checked.length === 0;
      return;
    }
    if (t === "text") {
      const v = (inputs.querySelector("textarea")?.value ?? "").trim();
      nextBtn.disabled = v.length === 0;
      return;
    }
    if (t === "number") {
      const v = (inputs.querySelector('input[type="number"]')?.value ?? "").trim();
      nextBtn.disabled = v.length === 0;
      return;
    }
    nextBtn.disabled = true;
  }

  function renderQuestion(q) {
    current = q;

    
    qTitle.textContent = q.title || "Вопрос";
    qText.textContent = q.text || "";
    qLong.textContent = (q.long_text || "").trim();

    const hints = (q.hints || "").trim();
    if (hints) {
      hintBox.classList.remove("hidden");
      qHints.textContent = hints;
    } else {
      hintBox.classList.add("hidden");
      qHints.textContent = "";
    }

    inputs.innerHTML = "";
    nextBtn.disabled = true;

    if (q.type === "single") {
      (q.options || []).forEach(opt => {
        const id = `s_${q.qid}_${opt.idx}`;
        const el = document.createElement("label");
        el.className = "opt";
        el.innerHTML = `
          <input type="radio" name="single" id="${id}" value="${opt.idx}">
          <div class="opt__text">${esc(opt.text)}</div>
        `;
        inputs.appendChild(el);
      });

      inputs.querySelectorAll('input[type="radio"]').forEach(r => {
        r.addEventListener("change", setEnabledByState);
      });
    }

    else if (q.type === "multi") {
      (q.options || []).forEach(opt => {
        const id = `m_${q.qid}_${opt.idx}`;
        const el = document.createElement("label");
        el.className = "opt";
        el.innerHTML = `
          <input type="checkbox" name="multi" id="${id}" value="${opt.idx}">
          <div class="opt__text">${esc(opt.text)}</div>
        `;
        inputs.appendChild(el);
      });

      inputs.querySelectorAll('input[type="checkbox"]').forEach(c => {
        c.addEventListener("change", setEnabledByState);
      });
    }

    else if (q.type === "text") {
      const el = document.createElement("textarea");
      el.className = "field";
      el.rows = 4;
      el.placeholder = "Введите текст…";
      el.addEventListener("input", setEnabledByState);
      inputs.appendChild(el);
    }

    else if (q.type === "number") {
      const el = document.createElement("input");
      el.className = "field";
      el.type = "number";
      el.step = "any";
      el.placeholder = "Введите число…";
      el.addEventListener("input", setEnabledByState);
      inputs.appendChild(el);
    }

    setEnabledByState();
  }

  function showResult(payload) {
    qCard.classList.add("hidden");
    resultBox.classList.remove("hidden");
    finalTitle.textContent = payload.final_title || "Готово";
    finalText.textContent = payload.final_text || "";
  }

  async function start() {
    const q = await fetchQuestion(startQid);
    if (!q.ok) throw new Error(q.error || "bad_response");
    renderQuestion(q);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!current) return;

    let body = { qid: current.qid, answers };

    if (current.type === "single") {
      const checked = inputs.querySelector('input[type="radio"][name="single"]:checked');
      if (!checked) return;
      body.option_idx = parseInt(checked.value, 10);
    }

    if (current.type === "multi") {
      const checked = Array.from(inputs.querySelectorAll('input[type="checkbox"][name="multi"]:checked'))
        .map(x => parseInt(x.value, 10));
      if (!checked.length) return;
      body.option_idxs = checked;
    }

    if (current.type === "text") {
      const v = (inputs.querySelector("textarea")?.value ?? "").trim();
      if (!v) return;
      body.value = v;
    }

    if (current.type === "number") {
      const v = (inputs.querySelector('input[type="number"]')?.value ?? "").trim();
      if (!v) return;
      body.value = v; // server will parse
    }

    const res = await fetch(`/api/s/${encodeURIComponent(surveyKey)}/answer`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)
    });

    const payload = await res.json();
    if (!payload.ok) {
      alert("Ошибка: " + (payload.error || "unknown"));
      return;
    }

    answers = payload.answers || answers;

    if (payload.finished) {
      showResult(payload);
      return;
    }

    const nextQ = await fetchQuestion(payload.next_qid);
    if (!nextQ.ok) {
      alert("Ошибка: не найден следующий вопрос");
      return;
    }
    renderQuestion(nextQ);
  });

  restartBtn.addEventListener("click", () => {
    answers = [];
    window.location.reload();
  });

  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const text = `${finalTitle.textContent}\n\n${finalText.textContent}`.trim();
      try {
        await navigator.clipboard.writeText(text);
        copyBtn.textContent = "Скопировано";
        setTimeout(() => (copyBtn.textContent = "Скопировать результат"), 1200);
      } catch {
        alert("Не удалось скопировать");
      }
    });
  }

  start().catch(() => alert("Не удалось загрузить опросник"));
})();
