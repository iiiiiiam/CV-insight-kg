// Framework-free detail component: mountPaperDetail(container, response, onNavigate).
// It renders text with textContent only and only allows http(s) source links.
function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function safeLink(url, label) {
  try {
    const u = new URL(url);
    if (!["https:", "http:"].includes(u.protocol)) throw 0;
    const a = el("a", label || url);
    a.href = u.href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  } catch {
    return el("span", "来源未提供");
  }
}
export function mountPaperDetail(root, data, onNavigate) {
  root.replaceChildren();
  const n = data.node;
  const card = el("article", undefined, "card");
  card.append(el("small", `${n.type} · ${data.batch_id}`), el("h1", n.name));
  const meta = el("div", undefined, "meta");
  meta.append(
    el("span", n.year ? `${n.year} 年` : "年份未提供"),
    el("span", `更新于 ${n.updated_at}`),
    safeLink(n.source_url, "查看来源"),
  );
  card.append(meta, el("h2", "摘要"), el("p", n.abstract || "摘要未提供"));
  if (n.missing_fields?.length)
    card.append(
      el("p", `缺失／未确认：${n.missing_fields.join("、")}`, "muted"),
    );
  card.append(el("h2", "实体关联与证据"));
  for (const r of data.relations) {
    const other = data.related.find(
      (x) => x.id === (r.source === n.id ? r.target : r.source),
    );
    const d = el("details");
    const s = el("summary", `${r.kind} → ${other?.name || r.target}`);
    d.append(s);
    if(r.review_state)d.append(el("p",`生成：${r.generation}；审核：${r.review_state}；规则调整：${r.rule_adjusted}`));
    if (other) {
      const b = el("button", "查看节点");
      b.onclick = () => onNavigate(other.id);
      d.append(b);
    }
    for (const e of r.evidence) {
      const q = el("blockquote", e.quote);
      d.append(
        q,
        el(
          "small",
          `${e.field} · ${e.locator ?? (e.field === "metadata" ? JSON.stringify(e.path) : `${e.start}:${e.end} code points`)} · ${r.review_state ?? "legacy confirmed"} · ${e.reviewer ?? "未提供逐条审核人"}`,
        ),
        el("br"),
        safeLink(e.source_url, "证据来源"),
      );
    }
    card.append(d);
  }
  if (!data.relations.length) card.append(el("p", "暂无当前有效关联。"));
  if (data.truncated)
    card.append(el("p", "关联超过 200 条，已截断；请使用图谱入口继续探索。"));
  root.append(card);
}
