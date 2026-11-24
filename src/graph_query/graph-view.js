// C reusable heterogeneous graph. No citation/similarity edges are inferred.
export const COLORS = {
  paper: "#267dba",
  author: "#9871bd",
  institution: "#de8d43",
  topic: "#3b9e76",
  method: "#d26489",
  task: "#6e8f48",
  dataset: "#30a6b0",
  venue: "#8794a3",
};
export function selectVisible(data, seed, hidden = new Set(), cap = 60) {
  const degree = new Map();
  for (const e of data.edges) {
    degree.set(e.source, (degree.get(e.source) || 0) + 1);
    degree.set(e.target, (degree.get(e.target) || 0) + 1);
  }
  const candidates = data.nodes
    .filter((n) => !hidden.has(n.kind || n.type.toLowerCase()))
    .sort(
      (a, b) =>
        (b.id === seed) - (a.id === seed) ||
        (a.hop ?? 1) - (b.hop ?? 1) ||
        (degree.get(b.id) || 0) - (degree.get(a.id) || 0) ||
        a.id.localeCompare(b.id),
    );
  const nodes = candidates.slice(0, cap),
    ids = new Set(nodes.map((n) => n.id));
  return {
    nodes,
    edges: data.edges.filter((e) => ids.has(e.source) && ids.has(e.target)),
    limited: candidates.length > cap,
    degree,
  };
}
// Compare identities, never infer new scientific relationships from layout.
export function expansion(one, two, seed) {
  const firstNodes = new Set(one.nodes.map((n) => n.id)),
    firstEdges = new Set(one.edges.map((e) => e.id));
  const nodes = new Map(
    [...one.nodes, ...two.nodes].map((n) => [
      n.id,
      {
        ...n,
        hop: n.id === seed ? 0 : firstNodes.has(n.id) ? 1 : 2,
        isNew: !firstNodes.has(n.id),
      },
    ]),
  );
  const edges = new Map(
    [...one.edges, ...two.edges].map((e) => [
      e.id,
      { ...e, isNew: !firstEdges.has(e.id) },
    ]),
  );
  return {
    ...two,
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    addedNodes: [...nodes.values()].filter((n) => n.isNew).map((n) => n.id),
    addedEdges: [...edges.values()].filter((e) => e.isNew).map((e) => e.id),
    baselineTruncated: !!one.truncated,
  };
}
export async function loadExpansion(load, params) {
  const requests =
    params.hops === 2
      ? [load({ ...params, hops: 1 }), load(params)]
      : [load(params)];
  const [one, two] = await Promise.all(requests);
  if (two && one.batch_id !== two.batch_id)
    throw Error("图谱批次不一致，请重新加载");
  return expansion(one, two || one, params.seed);
}
export function latestExpansion(load) {
  let sequence = 0;
  return {
    async run(params) {
      const token = ++sequence;
      const result = await loadExpansion(load, params);
      return token === sequence ? result : null;
    },
    cancel() {
      sequence++;
    },
  };
}
export function layout(nodes, edges) {
  const p = new Map(
    nodes.map((n, i) => [
      n.id,
      { x: 80 + (i % 8) * 110, y: 70 + Math.floor(i / 8) * 100 },
    ]),
  );
  for (let t = 0; t < 140; t++) {
    const f = new Map(nodes.map((n) => [n.id, { x: 0, y: 0 }]));
    for (let i = 0; i < nodes.length; i++)
      for (let j = i + 1; j < nodes.length; j++) {
        const a = p.get(nodes[i].id),
          b = p.get(nodes[j].id),
          dx = a.x - b.x || 0.1,
          dy = a.y - b.y || 0.2,
          d2 = Math.max(100, dx * dx + dy * dy),
          k = 4200 / d2;
        f.get(nodes[i].id).x += dx * k;
        f.get(nodes[i].id).y += dy * k;
        f.get(nodes[j].id).x -= dx * k;
        f.get(nodes[j].id).y -= dy * k;
      }
    for (const e of edges) {
      const a = p.get(e.source),
        b = p.get(e.target);
      if (!a || !b) continue;
      const dx = b.x - a.x,
        dy = b.y - a.y,
        d = Math.hypot(dx, dy) || 1,
        k = (d - 115) * 0.025;
      f.get(e.source).x += (dx / d) * k;
      f.get(e.source).y += (dy / d) * k;
      f.get(e.target).x -= (dx / d) * k;
      f.get(e.target).y -= (dy / d) * k;
    }
    for (const n of nodes) {
      const a = p.get(n.id),
        v = f.get(n.id);
      a.x += Math.max(-12, Math.min(12, v.x + (450 - a.x) * 0.004));
      a.y += Math.max(-12, Math.min(12, v.y + (260 - a.y) * 0.004));
    }
  }
  return p;
}
let serial = 0;
const NS = "http://www.w3.org/2000/svg";
function el(tag, text) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  return n;
}
function sv(tag, attrs) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  return n;
}
export function mountGraph(root, { load, seed, batch, onSelect = () => {} }) {
  const requests = latestExpansion(load);
  const markerId = "c-arrow-" + ++serial;
  root.replaceChildren();
  let data = { nodes: [], edges: [] },
    hidden = new Set(),
    positions = new Map(),
    selected = seed,
    view = "graph",
    camera = { x: 0, y: 0, k: 1 },
    seq = 0,
    disposed = false,
    loadedHops = 1;
  root.style.cssText =
    "font:14px/1.5 system-ui;color:#233f51;background:#f6f9fc;border:1px solid #cfdee7;border-radius:12px;padding:14px";
  const hoverInfo = el("p");
  const toolbar = el("div"),
    info = el("p"),
    legend = el("div"),
    stage = el("div"),
    panel = el("div"),
    list = el("div"),
    svg = sv("svg", {
      viewBox: "0 0 900 520",
      role: "img",
      "aria-label": "真实异构知识图谱，节点可拖动和选择",
    });
  svg.style.cssText =
    "width:100%;height:520px;background:white;touch-action:none;border-radius:8px";
  const hops = el("select");
  hops.setAttribute("aria-label", "图谱跳数");
  for (const h of [1, 2]) {
    const o = el("option", h + " 跳");
    o.value = h;
    hops.append(o);
  }
  function button(text, fn) {
    const b = el("button", text);
    b.type = "button";
    b.style.cssText = "margin:4px;padding:6px 10px;cursor:pointer";
    b.onclick = fn;
    toolbar.append(b);
    return b;
  }
  button("图谱视图", () => {
    view = "graph";
    draw();
  });
  button("列表视图", () => {
    view = "list";
    draw();
  });
  toolbar.append(hops);
  button("加载 / 展开", refresh);
  button("放大", () => zoom(1.25));
  button("缩小", () => zoom(0.8));
  button("适应画布", fit);
  button("重新布局", () => {
    positions = layout(current().nodes, current().edges);
    fit();
  });
  const typeNames = {
    paper: "论文",
    author: "作者",
    institution: "机构",
    topic: "主题",
    method: "方法",
    task: "任务",
    dataset: "数据集",
    venue: "会议",
  };
  for (const [k, color] of Object.entries(COLORS)) {
    const label = el("label"),
      box = el("input");
    box.type = "checkbox";
    box.checked = true;
    box.onchange = () => {
      box.checked ? hidden.delete(k) : hidden.add(k);
      positions = layout(current().nodes, current().edges);
      fit();
    };
    label.style.cssText = `display:inline-block;margin:5px;color:${color}`;
    label.append(box, " " + typeNames[k]);
    legend.append(label);
  }
  const hint = el(
    "p",
    "拖动节点调整布局，拖动画布平移；滚轮缩放。悬停或选择节点显示名称与真实关系。实线边框：一跳；紫色虚线边框：两跳新增。最多显示60个节点；可筛选类型或从选中节点重新探索。",
  );
  hint.style.color = "#5e7383";
  root.append(toolbar, legend, hint, info, hoverInfo, stage, panel);
  stage.append(svg, list);
  function current() {
    return selectVisible(data, seed, hidden);
  }
  function zoom(f) {
    camera.k = Math.max(0.15, Math.min(5, camera.k * f));
    draw();
  }
  function fit() {
    const v = current();
    if (!v.nodes.length) {
      camera = { x: 0, y: 0, k: 1 };
      draw();
      return;
    }
    const ps = [...positions.values()];
    const minX = Math.min(...ps.map((p) => p.x)),
      maxX = Math.max(...ps.map((p) => p.x)),
      minY = Math.min(...ps.map((p) => p.y)),
      maxY = Math.max(...ps.map((p) => p.y));
    const k = Math.min(2, 760 / (maxX - minX + 100), 400 / (maxY - minY + 100));
    camera = {
      k,
      x: 450 - ((minX + maxX) / 2) * k,
      y: 260 - ((minY + maxY) / 2) * k,
    };
    draw();
  }
  function showNode(n) {
    selected = n.id;
    draw();
    panel.replaceChildren(
      el("strong", n.name || n.label),
      el("p", `${n.type || n.kind} · ${n.id}`),
    );
    const edges = data.edges.filter(
      (e) => e.source === n.id || e.target === n.id,
    );
    for (const e of edges)
      panel.append(
        el(
          "p",
          `${e.source} → ${e.kind || e.type} → ${e.target} · ${e.review_state || e.status || "状态未提供"}`,
        ),
      );
    const b = el("button", "查看节点详情");
    b.type = "button";
    b.onclick = () => onSelect(n.id, batch);
    panel.append(b);
    const explore = el("button", "从此节点重新探索");
    explore.type = "button";
    explore.onclick = () => {
      seed = n.id;
      hops.value = "1";
      hidden.clear();
      for (const c of legend.querySelectorAll("input")) c.checked = true;
      refresh();
    };
    panel.append(explore);
    onSelect(n.id, batch);
  }
  function draw() {
    const v = current();
    svg.style.display = view === "graph" ? "block" : "none";
    list.hidden = view !== "list";
    info.textContent = `已加载 ${loadedHops} 跳 · 批次 ${batch} · 返回 ${data.nodes.length} 节点 / ${data.edges.length} 关系 · 显示 ${v.nodes.length} 节点 / ${v.edges.length} 关系${data.truncated ? " · 服务端路径上限已截断" : ""}${v.limited ? " · 画布60节点上限已截断" : ""}${loadedHops === 2 ? ` · 相对一跳新增 ${data.addedNodes.length} 节点 / ${data.addedEdges.length} 关系，画布显示新增 ${v.nodes.filter((n) => n.isNew).length} 节点` : ""}${loadedHops === 2 && !data.addedNodes.length && !data.addedEdges.length ? (data.truncated || data.baselineTruncated ? " · 当前截断范围未见新增，请换起点继续探索" : " · 没有发现新的两跳关联") : ""}`;
    list.replaceChildren();
    if (!v.nodes.length) list.append(el("p", "没有匹配的节点。"));
    for (const n of v.nodes) {
      const b = el("button", `${n.type || n.kind} · ${n.name || n.label}`);
      b.type = "button";
      b.onclick = () => showNode(n);
      list.append(b, el("br"));
    }
    svg.replaceChildren();
    const defs = sv("defs"),
      marker = sv("marker", {
        id: markerId,
        viewBox: "0 0 10 10",
        refX: 20,
        refY: 5,
        markerWidth: 5,
        markerHeight: 5,
        orient: "auto-start-reverse",
      });
    marker.append(sv("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: "#7792a3" }));
    defs.append(marker);
    svg.append(defs);
    const g = sv("g", {
      transform: `translate(${camera.x},${camera.y}) scale(${camera.k})`,
    });
    svg.append(g);
    const neighbours = new Set([selected]);
    for (const e of v.edges)
      if (e.source === selected || e.target === selected) {
        neighbours.add(e.source);
        neighbours.add(e.target);
      }
    for (const e of v.edges) {
      const a = positions.get(e.source),
        b = positions.get(e.target);
      if (!a || !b) continue;
      const active = e.source === selected || e.target === selected;
      const line = sv("line", {
        x1: a.x,
        y1: a.y,
        x2: b.x,
        y2: b.y,
        "data-source": e.source,
        "data-target": e.target,
        stroke: active ? "#436b87" : e.isNew ? "#9161b8" : "#cfdae3",
        "stroke-dasharray": e.isNew ? "5 3" : "none",
        "stroke-width": active ? 2 : 1,
        opacity: selected && selected !== seed && !active ? 0.25 : 1,
        "marker-end": `url(#${markerId})`,
      });
      const title = sv("title");
      title.textContent = e.kind || e.type;
      line.append(title);
      g.append(line);
      if (active) {
        const t = sv("text", {
          x: (a.x + b.x) / 2,
          y: (a.y + b.y) / 2 - 5,
          "font-size": 10,
          fill: "#47677d",
        });
        t.textContent = e.kind || e.type;
        g.append(t);
      }
    }
    const priority = [...v.nodes]
      .sort((a, b) => (v.degree.get(b.id) || 0) - (v.degree.get(a.id) || 0))
      .slice(0, 3)
      .map((n) => n.id);
    for (const n of v.nodes) {
      const p = positions.get(n.id);
      if (!p) continue;
      const group = sv("g", {
        "data-node": n.id,
        tabindex: 0,
        role: "button",
        "aria-label": n.name || n.label,
      });
      group.style.cursor = "grab";
      group.append(
        sv("circle", {
          cx: p.x,
          cy: p.y,
          r: n.id === seed ? 13 : 9,
          fill: COLORS[n.kind || n.type.toLowerCase()] || "#8794a3",
          stroke: n.id === selected ? "#172e40" : n.isNew ? "#9161b8" : "white",
          "stroke-dasharray": n.isNew ? "3 2" : "none",
          "stroke-width": 3,
          opacity:
            selected && selected !== seed && !neighbours.has(n.id) ? 0.3 : 1,
        }),
      );
      const title = sv("title");
      title.textContent = n.name || n.label;
      group.append(title);
      if (n.id === selected || n.id === seed || priority.includes(n.id)) {
        const t = sv("text", {
          x: p.x + 15,
          y: p.y + 4,
          "font-size": 12,
          fill: "#1c3649",
        });
        t.textContent = (n.name || n.label).slice(0, 32);
        group.append(t);
      }
      group.onclick = (e) => {
        if (e.detail === 0 && !moved) showNode(n);
      };
      group.onkeydown = (e) => {
        if (e.key === "Enter") showNode(n);
      };
      group.onpointerenter = () => {
        hoverInfo.textContent =
          (n.name || n.label) +
          " · " +
          (n.type || n.kind) +
          " · " +
          (n.hop === 2 ? "两跳新增" : "一跳/中心");
        for (const line of svg.querySelectorAll("line")) {
          const active =
            line.getAttribute("data-source") === n.id ||
            line.getAttribute("data-target") === n.id;
          line.style.opacity = active ? "1" : ".12";
          line.style.stroke = active ? "#244c69" : "";
        }
      };
      group.onpointerleave = () => {
        for (const line of svg.querySelectorAll("line")) {
          line.style.opacity = "";
          line.style.stroke = "";
        }
      };
      g.append(group);
    }
    if (v.nodes.length === 0) {
      const t = sv("text", { x: 30, y: 60, "font-size": 15 });
      t.textContent = "筛选后没有可显示节点。";
      svg.append(t);
    }
    if (v.nodes.length === 1 && !v.edges.length) {
      const t = sv("text", { x: 30, y: 480, "font-size": 15 });
      t.textContent = "该节点在当前范围内无关联，或关系已被筛选。";
      svg.append(t);
    }
  }
  let drag = null,
    moved = false;
  svg.onpointerdown = (e) => {
    const p = svg.createSVGPoint();
    p.x = e.clientX;
    p.y = e.clientY;
    const q = p.matrixTransform(svg.getScreenCTM().inverse());
    drag = {
      id: e.target.closest("[data-node]")?.getAttribute("data-node"),
      x: q.x,
      y: q.y,
    };
    moved = false;
    svg.setPointerCapture(e.pointerId);
  };
  svg.onpointermove = (e) => {
    if (!drag) return;
    const p = svg.createSVGPoint();
    p.x = e.clientX;
    p.y = e.clientY;
    const q = p.matrixTransform(svg.getScreenCTM().inverse()),
      dx = q.x - drag.x,
      dy = q.y - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 1) moved = true;
    if (drag.id) {
      const a = positions.get(drag.id);
      a.x += dx / camera.k;
      a.y += dy / camera.k;
    } else {
      camera.x += dx;
      camera.y += dy;
    }
    drag.x = q.x;
    drag.y = q.y;
    draw();
  };
  svg.onpointerup = (e) => {
    const id = drag?.id;
    drag = null;
    if (svg.hasPointerCapture(e.pointerId))
      svg.releasePointerCapture(e.pointerId);
    if (!moved && id) {
      const n = data.nodes.find((n) => n.id === id);
      if (n) showNode(n);
    }
  };
  svg.onpointercancel = () => {
    drag = null;
  };
  svg.onwheel = (e) => {
    e.preventDefault();
    zoom(e.deltaY < 0 ? 1.1 : 0.9);
  };
  async function refresh() {
    const token = ++seq;
    info.textContent = "正在读取已发布图谱…";
    try {
      const requestedHops = Number(hops.value);
      const d = await requests.run({
        seed,
        batch_id: batch,
        hops: requestedHops,
        limit: 60,
      });
      if (!d || disposed || token !== seq) return;
      data = d;
      loadedHops = requestedHops;
      selected = seed;
      positions = layout(current().nodes, current().edges);
      panel.replaceChildren();
      fit();
    } catch (e) {
      if (token === seq) info.textContent = "图谱读取失败：" + e.message;
    }
  }
  refresh();
  return {
    destroy() {
      disposed = true;
      seq++;
      requests.cancel();
      root.replaceChildren();
    },
    refresh,
  };
}
