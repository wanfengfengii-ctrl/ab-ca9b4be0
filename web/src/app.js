/* 双应答机脉冲联合判读前端（零依赖原生 JS）。 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const timesEl = $("times");
  const hintEl = $("timesHint");
  const formError = $("formError");
  const runBtn = $("run");
  const reportEl = $("report");

  const SAMPLE = "0 7 44 50 81 100 118 150 155 192 200";

  $("sample").addEventListener("click", () => {
    timesEl.value = SAMPLE;
    parseTimes(true);
  });

  timesEl.addEventListener("input", () => parseTimes(false));

  function parseTimes(quiet) {
    const raw = timesEl.value.trim();
    const parts = raw.split(/[\s,，;；]+/).filter(Boolean);
    if (!quiet) formError.textContent = "";
    if (parts.length === 0) {
      setHint("", "");
      return null;
    }
    const nums = [];
    for (const p of parts) {
      if (!/^\d+$/.test(p)) {
        setHint(`「${p}」不是整数`, "bad");
        return null;
      }
      nums.push(parseInt(p, 10));
    }
    if (nums.length < 8 || nums.length > 16) {
      setHint(`当前 ${nums.length} 条，需要 8–16 条`, "bad");
      return null;
    }
    for (let i = 1; i < nums.length; i++) {
      if (nums[i] <= nums[i - 1]) {
        setHint(`第 ${i + 1} 条（${nums[i]}）未严格大于前一条（${nums[i - 1]}）`,
                "bad");
        return null;
      }
    }
    setHint(`已识别 ${nums.length} 条严格递增脉冲`, "good");
    return nums;
  }

  function setHint(text, cls) {
    hintEl.textContent = text;
    hintEl.className = "hint " + (cls || "");
  }

  function readMachine(prefix) {
    return {
      period_min: num(prefix + "_min"),
      period_max: num(prefix + "_max"),
      tolerance: num(prefix + "_tol"),
      max_missing: num(prefix + "_miss"),
    };
  }
  function num(id) { return parseInt($(id).value, 10); }

  function validateSpecs(a, b) {
    for (const [name, s] of [["A", a], ["B", b]]) {
      if (!(s.period_min >= 10 && s.period_max <= 200
            && s.period_min <= s.period_max)) {
        return `应答机 ${name} 周期区间需满足 10 ≤ 下限 ≤ 上限 ≤ 200`;
      }
      if (s.tolerance < 0 || s.max_missing < 0) {
        return `应答机 ${name} 误差与漏收数不能为负`;
      }
    }
    return null;
  }

  runBtn.addEventListener("click", async () => {
    const times = parseTimes(true);
    const ma = readMachine("a"), mb = readMachine("b");
    const specErr = validateSpecs(ma, mb);
    if (!times) { formError.textContent = "请先修正到达时刻输入"; return; }
    if (specErr) { formError.textContent = specErr; return; }
    formError.textContent = "";

    runBtn.disabled = true;
    reportEl.classList.remove("hidden");
    reportEl.innerHTML = '<div class="loading">正在联合搜索两台整数周期…</div>';

    try {
      const resp = await fetch("/api/interpret", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ times, machine_a: ma, machine_b: mb }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        const detail = typeof data.detail === "string"
          ? data.detail : JSON.stringify(data.detail);
        reportEl.innerHTML = "";
        reportEl.appendChild(renderErrorCard("请求被拒绝（422）", detail));
        return;
      }
      render(data);
    } catch (err) {
      reportEl.innerHTML = "";
      reportEl.appendChild(renderErrorCard("API 不可达", String(err)));
    } finally {
      runBtn.disabled = false;
    }
  });

  // ------------------------------------------------------------------
  // 渲染
  // ------------------------------------------------------------------

  function render(data) {
    reportEl.innerHTML = "";
    if (!data.feasible) {
      reportEl.appendChild(renderFailure(data.diagnosis));
      return;
    }
    if (data.tied) {
      reportEl.appendChild(renderTieBanner(data));
    }
    data.solutions.forEach((sol, i) => {
      if (data.solutions.length > 1) {
        const h = el("h3", "witness-title",
          `完整见证 ${i + 1}　周期 A=${sol.periods.A} µs / B=${sol.periods.B} µs`);
        reportEl.appendChild(h);
      }
      reportEl.appendChild(renderSolution(sol));
    });
  }

  function renderTieBanner(data) {
    const d = data.first_divergence || {};
    let body = "存在两套目标值并列（噪声数与漏收总数均相同）的完整最优见证，已一并报告。";
    if (d.period_note) body += "<br>" + esc(d.period_note);
    if (d.index !== null && d.index !== undefined) {
      body += `<br>第一条归属分歧：脉冲 #${d.index + 1}（t=${d.time}），`
            + `见证一判为 <span class="candidate">${labelZh(d.labels[0])}</span>，`
            + `见证二判为 <span class="candidate">${labelZh(d.labels[1])}</span>；`
            + `该脉冲之前的归属两套完全一致。`;
    } else {
      body += "<br>两套见证对每条脉冲的归属一致，仅推得周期不同。";
    }
    return el("div", "tie-banner", body);
  }

  function renderSolution(sol) {
    const frag = document.createDocumentFragment();

    const summary = el("div", "summary-row",
      `<span>应答机 A 推得周期 <b>${sol.periods.A} µs</b></span>`
      + `<span>应答机 B 推得周期 <b>${sol.periods.B} µs</b></span>`
      + `<span>噪声 <b>${sol.noise_count}</b> 条</span>`
      + `<span>两台漏收合计 <b>${sol.missing_total}</b> 个</span>`);
    frag.appendChild(summary);

    // 归属顺序色带
    const strip = el("div", "pulse-strip", "");
    strip.style.cssText = "display:flex;gap:4px;flex-wrap:wrap;margin:4px 0 14px;";
    sol.pulses.forEach((p) => {
      const chip = el("span", "badge " + badgeClass(p.assignment),
        `${p.index + 1}@${p.time}`);
      chip.title = labelZh(p.assignment);
      strip.appendChild(chip);
    });
    frag.appendChild(strip);

    // 每条脉冲明细表
    let html = "<table><thead><tr>"
      + "<th>#</th><th>到达 (µs)</th><th>归属</th><th>周期数 k</th>"
      + "<th>补漏收</th><th>本段误差 (µs)</th>"
      + "</tr></thead><tbody>";
    sol.pulses.forEach((p) => {
      html += `<tr class="row-${p.assignment}">`
        + `<td>${p.index + 1}</td><td>${p.time}</td>`
        + `<td><span class="badge ${badgeClass(p.assignment)}">`
        + `${labelZh(p.assignment)}</span></td>`
        + `<td>${p.cycles ?? "—"}</td>`
        + `<td>${p.missing_before ?? "—"}</td>`
        + `<td>${fmtErr(p.segment_error)}</td></tr>`;
    });
    html += "</tbody></table>";
    frag.appendChild(el("div", "", html));

    // 两台设备分段
    ["A", "B"].forEach((name) => {
      const m = sol.machines[name];
      const block = el("div", `machine-block for-${name}`, "");
      block.appendChild(el("h3", "",
        `应答机 ${name} · 周期 ${m.period} µs · 采用 ${m.adopted_count} 条`
        + ` · 漏收 ${m.missing_total} 个`));
      block.appendChild(el("div", "meta",
        "同台相邻采用脉冲间隔须等于正整数个周期；下表逐段列出 k、间隔残差与误差限。"));
      let sh = "<table><thead><tr><th>从</th><th>到</th><th>间隔</th>"
        + "<th>k</th><th>期望间隔</th><th>残差</th><th>误差限</th><th>漏收</th>"
        + "</tr></thead><tbody>";
      m.segments.forEach((s) => {
        sh += `<tr><td>#${s.from_index + 1} @${s.from_time}</td>`
          + `<td>#${s.to_index + 1} @${s.to_time}</td>`
          + `<td>${s.gap}</td><td>${s.cycles}</td>`
          + `<td>${s.expected_gap}</td>`
          + `<td style="color:${Math.abs(s.error) > s.error_limit
              ? "var(--err)" : "inherit"}">${fmtErr(s.error)}</td>`
          + `<td>±${s.error_limit}</td><td>${s.missing}</td></tr>`;
      });
      sh += "</tbody></table>";
      block.appendChild(el("div", "", sh));
      frag.appendChild(block);
    });
    return frag;
  }

  function renderErrorCard(title, message) {
    return el("div", "fail-card",
      `<h3>${esc(title)}</h3><div class="reason">${esc(message)}</div>`);
  }

  function renderFailure(d) {
    const box = el("div", "fail-card", "");
    box.appendChild(el("h3", "", "不存在联合解释 —— 已清除旧报告"));
    box.appendChild(el("div", "",
      `<div>按到达时刻顺序，<b>第一个无法延续</b>的脉冲是 `
      + `<span class="candidate">第 ${d.pulse_no} 条（t=${d.time} µs）</span>。</div>`
      + `<div style="color:var(--muted);margin-top:4px;">它之前的脉冲还能形成`
      + `局部合法的前缀，但把该脉冲作为噪声或归属任一台应答机，都无法继续。</div>`));
    d.reasons.forEach((r) => {
      const who = r.device === "noise" ? "候选：作为噪声"
        : r.device === "all" ? "总体原因"
        : `候选：归属应答机 ${r.device}`;
      const row = el("div", "reason",
        `<span class="candidate">${esc(who)}</span> —— ${esc(r.message)}`);
      box.appendChild(row);
    });
    return box;
  }

  // ------------------------------------------------------------------
  // 小工具
  // ------------------------------------------------------------------

  function labelZh(a) {
    return a === "A" ? "应答机 A" : a === "B" ? "应答机 B" : "噪声";
  }
  function badgeClass(a) {
    return a === "A" ? "a" : a === "B" ? "b" : "noise";
  }
  function fmtErr(v) {
    if (v === null || v === undefined) return "—";
    return (v > 0 ? "+" : "") + v;
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
                '"': "&quot;", "'": "&#39;" }[c]));
  }
  function el(tag, cls, html) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (html !== undefined && html !== null) node.innerHTML = html;
    return node;
  }
})();
