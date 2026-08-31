(() => {
  "use strict";

  const cleanDisplayText = (text) => String(text || "")
    .replace(/¶/g, " ")
    .replace(/^[\s`←→]+/, "")
    .replace(/\s+/g, " ")
    .trim();

  const integerToKanji = (value) => {
    const number = Number(value);
    if (!Number.isSafeInteger(number) || number <= 0 || number > 9999) return value;
    const digits = "〇一二三四五六七八九";
    const units = [[1000, "千"], [100, "百"], [10, "十"]];
    let remainder = number;
    let rendered = "";
    for (const [size, label] of units) {
      const digit = Math.floor(remainder / size);
      if (digit) rendered += `${digit === 1 ? "" : digits[digit]}${label}`;
      remainder %= size;
    }
    if (remainder) rendered += digits[remainder];
    return rendered;
  };

  const normalizeLegalQuery = (term) => String(term || "").replace(
    /第([0-9]+)条(?:の([0-9]+))?/g,
    (_match, article, branch) => `第${integerToKanji(article)}条${branch ? `の${integerToKanji(branch)}` : ""}`,
  );

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { cleanDisplayText, normalizeLegalQuery };
  }
  if (typeof document === "undefined") return;

  const root = document.querySelector("[data-finlaws-search]");
  if (!root) return;

  const form = root.querySelector("form");
  const input = root.querySelector("input[type='search']");
  const status = root.querySelector("[data-search-status]");
  const results = root.querySelector("[data-search-results]");
  let searchModules;
  let requestSerial = 0;

  const setStatus = (message) => {
    status.textContent = message;
  };

  const plainExcerpt = (html) => {
    const documentFragment = new DOMParser().parseFromString(html || "", "text/html");
    return cleanDisplayText(documentFragment.body.textContent);
  };

  const loadModules = async () => {
    if (searchModules) return searchModules;
    searchModules = (async () => {
      const manifestUrl = new URL(root.dataset.pagefindManifest, window.location.href);
      const response = await fetch(manifestUrl);
      if (!response.ok) throw new Error(`検索設定を読み込めませんでした (${response.status})`);
      const manifest = await response.json();
      const modules = await Promise.all(
        manifest.partitions.map(async (partition) => {
          const moduleUrl = new URL(`${partition.bundle}pagefind.js`, manifestUrl);
          const module = await import(moduleUrl.href);
          await module.options({ baseUrl: manifest.base_path });
          return { name: partition.name, module };
        }),
      );
      return modules;
    })();
    return searchModules;
  };

  const renderResults = (items, term) => {
    results.replaceChildren();
    if (!items.length) {
      setStatus(`「${term}」に一致する条文はありません。`);
      return;
    }
    setStatus(`${items.length}件を表示しています。`);
    for (const item of items) {
      const row = document.createElement("li");
      row.className = "finlaws-search-result";
      const link = document.createElement("a");
      link.href = item.url;
      link.textContent = cleanDisplayText(item.meta?.title) || item.url;
      const excerpt = document.createElement("p");
      excerpt.textContent = plainExcerpt(item.excerpt);
      row.append(link, excerpt);
      results.append(row);
    }
  };

  const search = async (term) => {
    const serial = ++requestSerial;
    if (!term) {
      results.replaceChildren();
      setStatus("法令名、制度名、条番号を入力してください。");
      return;
    }
    setStatus("検索索引を読み込んでいます…");
    try {
      const modules = await loadModules();
      const partitionResults = await Promise.all(
        modules.map(async ({ module }) => module.search(normalizeLegalQuery(term))),
      );
      const references = partitionResults
        .flatMap((result) => result.results)
        .sort((left, right) => right.score - left.score)
        .slice(0, 40);
      const loaded = await Promise.all(references.map((reference) => reference.data()));
      const unique = [];
      const seen = new Set();
      for (const item of loaded) {
        if (seen.has(item.url)) continue;
        seen.add(item.url);
        unique.push(item);
        if (unique.length === 20) break;
      }
      if (serial === requestSerial) renderResults(unique, term);
    } catch (error) {
      if (serial !== requestSerial) return;
      console.error(error);
      results.replaceChildren();
      setStatus("検索索引を読み込めませんでした。ページを再読み込みしてください。");
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    search(input.value.trim());
  });
})();
