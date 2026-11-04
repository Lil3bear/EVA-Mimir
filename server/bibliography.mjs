import { parse } from "@retorquere/bibtex-parser";
import { setTimeout as sleep } from "node:timers/promises";

export function safeArticleURL(value) {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
const normalize = value => String(value || "").normalize("NFKC").toLowerCase().replace(/<[^>]*>/g, "").replace(/[^\p{L}\p{N}]/gu, "");
export function bibliography(files) {
  const entries = [], issues = [], keys = new Set(), identifiers = new Map();
  for (const [file, encoded] of Object.entries(files)) {
    if (!/\.bib$/i.test(file)) continue;
    let library;
    try { library = parse(Buffer.from(encoded, "base64").toString("utf8")); }
    catch (error) { issues.push({file, message: `Bib 解析失败：${error.message}`}); continue; }
    for (const error of library.errors) issues.push({ file, message: String(error.message || error) });
    for (const item of library.entries) {
      const f = item.fields, problems = [];
      const doi = String(f.doi || "").replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "").replace(/^doi:\s*/i, "").trim();
      if (keys.has(item.key)) problems.push("重复引用键，无法可靠关联");
      keys.add(item.key);
      if (!f.title) problems.push("缺少标题");
      if (!f.author?.length && !f.editor?.length && !f.organization) problems.push("缺少作者、编辑或机构");
      if (!f.year && !f.date) problems.push("缺少年份");
      if (doi && !/^10\.\d{4,9}\/\S+$/i.test(doi)) problems.push("DOI 格式异常");
      for (const id of [doi && `doi:${doi.toLowerCase()}`, f.title && `title:${normalize(f.title)}`].filter(Boolean)) {
        if (identifiers.has(id)) problems.push(`与 ${identifiers.get(id)} 的 DOI 或标题重复`);
        identifiers.set(id, item.key);
      }
      const arxiv = /arxiv/i.test(String(f.archiveprefix || f.eprinttype || "")) && /^[\w.-]+(?:\/\d+)?$/.test(String(f.eprint || "")) ? `https://arxiv.org/abs/${f.eprint}` : null;
      const url = (doi && /^10\.\d{4,9}\/\S+$/i.test(doi) ? `https://doi.org/${encodeURI(doi).replace(/[?#]/g, c => encodeURIComponent(c))}` : null) || safeArticleURL(f.url) || arxiv;
      if (!url) problems.push("缺少可打开的 DOI、URL 或 arXiv 标识");
      entries.push({ key: item.key, file, title: String(f.title || ""), year: String(f.year || f.date || ""), authors: (Array.isArray(f.author) ? f.author : []).map(a => a.lastName || a.name || ""), doi, url, problems });
    }
  }
  // Only identify explicit citation commands; this is not a TeX macro interpreter.
  for (const [file, encoded] of Object.entries(files)) {
    if (!/\.tex$/i.test(file)) continue;
    const source = Buffer.from(encoded, "base64").toString("utf8").replace(/(?<!\\)%[^\n]*/g, "");
    for (const match of source.matchAll(/\\(?:cite[a-zA-Z]*|nocite)\*?(?:\s*\[[^\]]*\])*\s*\{([^}]*)\}/g)) {
      for (const key of match[1].split(",").map(k => k.trim())) {
        if (key !== "*" && !keys.has(key)) issues.push({file, message: key ? `引用键未定义：${key}` : "存在空引用"});
      }
    }
  }
  // Every duplicate must be excluded from clickable mappings, not just the last one.
  for (const entry of entries) if (entries.filter(e => e.key === entry.key).length > 1 && !entry.problems.some(p => p.startsWith("重复引用键"))) entry.problems.push("重复引用键，无法可靠关联");
  return { entries, issues };
}

export async function verifyEntry(entry, { signal, fetcher = fetch } = {}) {
  const url = entry.doi ? `https://api.crossref.org/works/${encodeURIComponent(entry.doi)}` : `https://api.crossref.org/works?${new URLSearchParams({"query.bibliographic": entry.title, "query.author": entry.authors[0] || "", rows: "3"})}`;
  if (!entry.title) return { status: "unverified", detail: "缺少标题，未查询" };
  try {
    let response;
    for (let attempt = 0; attempt < 3; attempt++) {
      response = await fetcher(url, { signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(12000)]) : AbortSignal.timeout(12000), headers: { "User-Agent": "Autopaperreview/0.1 (bibliography metadata audit)" } });
      if (response.status !== 429 || attempt === 2) break;
      const retryAfter = Number(response.headers?.get("retry-after"));
      await response.body?.cancel();
      await sleep(Math.min(60, Math.max(2 ** (attempt + 1), retryAfter || 0)) * 1000, undefined, { signal });
    }
    if (!response.ok) return { status: "unverified", detail: `Crossref 返回 ${response.status}；不能据此判定文献不存在` };
    const data = await response.json();
    const work = entry.doi ? data.message : data.message?.items?.find(w => normalize(w.title?.[0]) === normalize(entry.title)) || data.message?.items?.[0];
    if (!work) return { status: "unverified", detail: "Crossref 未找到记录；不等于文献不存在" };
    const titleMatches = normalize(work.title?.[0]) === normalize(entry.title);
    const years = [work.published, work["published-print"], work["published-online"], work.issued].flatMap(v => v?.["date-parts"]?.map(p => String(p[0])) || []);
    const yearMatches = years.includes(entry.year.slice(0,4));
    const namedAuthors = entry.authors.filter(a => a !== "others");
    const authorMatches = namedAuthors.length > 0 && namedAuthors.every(a => work.author?.some(b => normalize(b.family || b.name) === normalize(a)));
    const validDOI = /^10\.\d{4,9}\/\S+$/i.test(work.DOI || "");
    const mismatches = [!titleMatches && "标题", !yearMatches && "年份", !authorMatches && "作者", (!validDOI || entry.doi && entry.doi.toLowerCase() !== work.DOI.toLowerCase()) && "DOI"].filter(Boolean);
    return {
      status: mismatches.length ? (entry.doi ? "mismatch" : "candidate") : "verified",
      detail: mismatches.length ? `${mismatches.join("、")}不一致或信息不足，需人工核对` : "标题、年份和作者姓氏与 Crossref 元数据一致（不代表已核查原文论据）",
      title: work.title?.[0], doi: work.DOI,
      url: validDOI ? safeArticleURL(`https://doi.org/${work.DOI}`) : null,
      checked: new Date().toISOString(),
    };
  } catch (error) {
    signal?.throwIfAborted();
    return { status: "unverified", detail: `查询失败：${error.message}` };
  }
}
