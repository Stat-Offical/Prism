(() => {
  "use strict";
  const data = window.PRISM_DATA || { meta: {}, articles: [], rssTitles: [] };
  const main = document.getElementById("main");
  const state = { article: null, order: null, returnFocus: null };
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const date = value => (value || "").slice(0, 10).replaceAll("-", ".");
  const url = article => `#/article/${article.id}`;
  const image = (article, lazy = true) => `<img src="${esc(article.imageUrl || "assets/cover.svg")}" alt="" width="900" height="540" loading="${lazy ? "lazy" : "eager"}" decoding="async" referrerpolicy="no-referrer" data-news-image>`;
  function readable(value) {
    const text = String(value ?? "");
    let html = "", cursor = 0;
    for (const match of text.matchAll(/[+−△]?\d+(?:[,.]\d+)*/g)) {
      html += esc(text.slice(cursor, match.index)) + `<span class="num">${esc(match[0])}</span>`;
      cursor = match.index + match[0].length;
    }
    return html + esc(text.slice(cursor));
  }
  function shuffle(values) {
    const result = [...values];
    for (let i = result.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
  }
  function newsCard(article, kind = "news-card") {
    return `<article class="news-story ${kind}" data-news-id="${article.id}"><a href="${url(article)}"><div class="image-wrap">${image(article)}</div><div class="article-label">뉴스</div><h2>${readable(article.title)}</h2><p class="lead-deck">${readable(article.summary)}</p><div class="byline"><span>${esc(article.publisher)}</span><time datetime="${esc(article.providedAt)}">${date(article.providedAt)}</time></div></a>${kind === "related-card" ? "" : `<div class="news-sources"><span>검색 기준</span>${article.rssTitles.map(title => `<span class="rss-source">${esc(title)}</span>`).join("")}</div>`}</article>`;
  }
  function home(params) {
    state.article = null;
    const query = params.get("q")?.trim() || "";
    document.getElementById("search").value = query;
    document.title = "Prism · 하나의 자료, 여러 시선";
    if (!state.order) state.order = shuffle(data.articles.map(article => article.id));
    const order = new Map(state.order.map((id, index) => [id, index]));
    const pool = data.articles.filter(article =>
      !query || `${article.title} ${article.summary} ${article.queries.join(" ")}`.toLowerCase().includes(query.toLowerCase())
    ).sort((a, b) => Number(Boolean(b.body)) - Number(Boolean(a.body)) || order.get(a.id) - order.get(b.id));
    const selected = pool.slice(0, 24);
    let html = `<div class="home-heading"><h1>${query ? `‘${esc(query)}’ 검색 결과` : "통계로 읽는 뉴스"}</h1><div class="home-actions"><span>${pool.length}건</span><button id="shuffle-news" type="button" ${pool.length < 2 ? "disabled" : ""}>다시 섞기 ↻</button></div></div>`;
    if (!selected.length) {
      html += `<div class="empty-search"><h2>표시할 뉴스가 없습니다.</h2><p>${query ? "다른 검색어를 입력해 보세요." : "수집한 뉴스가 준비되면 여기에 표시됩니다."}</p></div>`;
    } else if (query) {
      html += `<div class="news-grid">${selected.map(article => newsCard(article)).join("")}</div>`;
    } else {
      const recent = [...data.articles].sort((a, b) => b.providedAt.localeCompare(a.providedAt)).slice(0, 5);
      html += `<section class="lead-grid" aria-label="주요 뉴스">${newsCard(selected[0], "lead-feature")}<div class="lead-secondary">${selected.slice(1, 3).map(article => newsCard(article, "secondary-story")).join("")}</div><aside class="rail"><div class="rail-heading"><h2>최근 뉴스</h2></div>${recent.map(article => `<a class="rail-story" href="${url(article)}"><time>${date(article.providedAt)}</time><h3>${readable(article.title)}</h3></a>`).join("")}</aside></section>`;
      if (selected.length > 3) html += `<section><div class="section-heading"><h2>더 많은 뉴스</h2></div><div class="news-grid">${selected.slice(3).map(article => newsCard(article)).join("")}</div></section>`;
    }
    main.innerHTML = html;
  }
  function bodyHtml(article) {
    if (!article.body) return `<div class="body-unavailable"><h2>검색 요약</h2><p>${readable(article.summary)}</p><p class="body-notice">${article.bodyStatus === "not_requested" ? "아직 본문이 수집되지 않았습니다." : "본문을 불러오지 못했습니다."} 언론사 원문에서 확인해 주세요.</p></div>`;
    return article.body.split(/\r?\n/).filter(line => line.trim()).map(line => `<p>${readable(line)}</p>`).join("");
  }
  function articlePage(id) {
    const article = data.articles.find(item => item.id === id);
    state.article = article || null;
    document.getElementById("search").value = "";
    if (!article) {
      main.innerHTML = '<div class="empty-search"><h1>기사를 찾을 수 없어요.</h1><a class="text-button" href="#/">첫 화면으로 →</a></div>';
      return;
    }
    document.title = `${article.title} · Prism`;
    main.innerHTML = `<div class="article-topline"><a href="#/">홈</a><span>/ 뉴스</span></div>
      <div class="reading-layout"><article class="reading-column">
        <header class="article-header"><div class="article-label">뉴스</div><h1>${readable(article.title)}</h1><div class="article-meta"><span class="source-name">${esc(article.publisher)}</span>${article.providedAt ? `<time datetime="${esc(article.providedAt)}">네이버 제공 ${date(article.providedAt)} ${article.providedAt.slice(11, 16)}</time>` : ""}<a href="${esc(article.url)}" target="_blank" rel="noopener noreferrer">원문 보기 ↗</a></div></header>
        <figure class="article-visual">${image(article, false)}</figure>
        <section class="article-body" aria-label="기사 본문">${bodyHtml(article)}</section>
        <section class="source-box"><h2>검색 기준 RSS 제목</h2><div class="source-titles">${article.rssTitles.map(title => `<span>${esc(title)}</span>`).join("")}</div></section>
      </article><aside class="related-panel" id="related-panel" aria-labelledby="related-heading"></aside></div>
      <button type="button" class="mobile-panel-trigger" id="open-panel">관련 기사 보기 ↑</button>
      <button type="button" class="sheet-backdrop" id="sheet-backdrop" tabindex="-1" aria-label="관련 기사 닫기"></button>
      <p id="panel-status" class="sr-only" role="status" aria-live="polite"></p>`;
    renderPanel();
  }
  function relatedArticles() {
    const queries = new Set(state.article.queries);
    const rank = article => Math.min(...state.article.queries.map(query => article.queryRanks?.[query] ?? Infinity));
    return data.articles.filter(article => article.id !== state.article.id && article.queries.some(query => queries.has(query)))
      .sort((a, b) => rank(a) - rank(b)).slice(0, 8);
  }
  function renderPanel() {
    const articles = relatedArticles();
    const panel = document.getElementById("related-panel");
    panel.innerHTML = `<div class="panel-heading"><h2 id="related-heading">연관 기사</h2><button id="close-panel" class="mobile-close" type="button" aria-label="관련 기사 닫기">×</button></div>
      <div class="panel-controls"><span class="panel-count">${articles.length}건</span><span>관련성순</span></div>
      <p class="candidate-note">같은 검색어로 수집한 기사입니다.</p>
      <div id="related-list">${articles.length ? articles.map(article => newsCard(article, "related-card")).join("") : '<p class="panel-empty">연관 기사가 없습니다.</p>'}</div>`;
    document.getElementById("panel-status").textContent = `연관 기사 ${articles.length}건`;
  }
  function toggleInert(value) {
    [".site-header", ".site-footer", ".article-topline", ".reading-column", "#open-panel"].forEach(selector => {
      const element = document.querySelector(selector);
      if (element) element.inert = value;
    });
  }
  function openPanel() {
    const panel = document.getElementById("related-panel");
    if (!window.matchMedia("(max-width: 760px)").matches) { panel?.scrollIntoView({ block: "start" }); return; }
    state.returnFocus = document.activeElement;
    document.body.classList.add("sheet-open");
    toggleInert(true);
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    document.getElementById("close-panel").focus({ preventScroll: true });
  }
  function closePanel(restoreFocus = true) {
    if (!document.body.classList.contains("sheet-open")) return;
    document.body.classList.remove("sheet-open");
    toggleInert(false);
    const panel = document.getElementById("related-panel");
    panel?.removeAttribute("role");
    panel?.removeAttribute("aria-modal");
    if (restoreFocus) state.returnFocus?.focus({ preventScroll: true });
  }
  function route() {
    closePanel(false);
    const [path, query = ""] = location.hash.slice(1).split("?");
    const params = new URLSearchParams(query), match = /^\/article\/([a-f0-9]{20})$/.exec(path);
    if (match) articlePage(match[1]); else home(params);
    window.scrollTo(0, 0);
  }
  document.addEventListener("error", event => {
    const target = event.target;
    if (!target.matches?.("img[data-news-image]") || target.dataset.fallback) return;
    target.dataset.fallback = "true";
    target.src = "assets/cover.svg";
  }, true);
  document.addEventListener("click", event => {
    const id = event.target.closest("button")?.id;
    if (id === "shuffle-news") { state.order = shuffle(data.articles.map(article => article.id)); home(new URLSearchParams(location.hash.split("?")[1] || "")); }
    if (id === "open-panel") openPanel();
    if (id === "close-panel" || id === "sheet-backdrop") closePanel();
    if (id === "footer-info") document.getElementById("info-dialog").showModal();
    if (id === "info-close") document.getElementById("info-dialog").close();
  });
  document.addEventListener("keydown", event => {
    if (!document.body.classList.contains("sheet-open")) return;
    if (event.key === "Escape") { event.preventDefault(); closePanel(); return; }
    if (event.key !== "Tab") return;
    const items = [...document.querySelectorAll("#related-panel a[href], #related-panel button")].filter(el => el.getClientRects().length);
    const first = items[0], last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  });
  document.getElementById("search-form").addEventListener("submit", event => {
    event.preventDefault();
    location.hash = `/?q=${encodeURIComponent(document.getElementById("search").value.trim())}`;
  });
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", () => { if (!window.matchMedia("(max-width: 760px)").matches) closePanel(false); });
  route();
})();
