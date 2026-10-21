import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const skills = [
  {
    id: "snap-write",
    name: "Snap Write · 局部学术润色",
    group: "写作",
    default: false,
    source: "作者指定的局部写作规范",
    files: ["skills/snap-write/SKILL.md"],
    description: "保留逻辑和信息量，准确使用术语；自然学术表达，避免长难句、机器人碎句和说明书式写法。",
  },
  ...[
    ["paper-figure-story", "图示 · 动机与创新", "https://github.com/Leey21/awesome-ai-research-writing", "全文证据对齐、Method 审查与图示主张边界。"],
    ["paper-figure-layout", "图示 · 六类布局", "https://paper-banana.org/zh/blog/figure-1-layout-patterns", "按信息关系选择布局，突出动机与创新，检查阅读顺序。"],
    ["scientific-illustration", "图示 · 科学插画", "https://github.com/Leey21/awesome-ai-research-writing", "作者提供的绘图模板、可编辑矢量元素、标注与视觉终检。"],
    ["experiment-figures", "图示 · 实验图表", "https://github.com/Leey21/awesome-ai-research-writing", "从原始表格取数，区分实验条件，不编造误差棒或实验。"],
  ].map(([id,name,sourceURL,description])=>({id,name,group:"绘图",default:false,source:id==="paper-figure-layout"?"PaperBanana · Figure 1 布局":"作者模板与 Leey21；独立整理",sourceURL,files:[`skills/${id}/SKILL.md`,...(id==="scientific-illustration"?["skills/scientific-illustration/references/illustrator-prompt.md"]:[])],description})),
  {
    id: "writing",
    name: "学术表达",
    group: "写作",
    source: "Leey21/awesome-ai-research-writing",
    required: true,
    files: ["skills/writing.md", "skills/modules/contracts.md", "skills/modules/provenance.json", "skills/modules/writing.md"],
    description: "学术表达、术语一致性与简洁改写；保留作者原意。",
  },
  {
    id: "writing-ai-paper",
    name: "WritingAIPaper 全文对齐",
    group: "写作",
    source: "hzwer/WritingAIPaper",
    sourceURL: "https://github.com/hzwer/WritingAIPaper",
    required: true,
    files: ["skills/writing-ai-paper/SKILL.md", "skills/writing-ai-paper/references/checklist.md", "skills/writing-ai-paper/references/provenance.json"],
    description: "检查全文主线、论断证据、实验诚信和作者指定的简洁风格。",
  },
  {
    id: "zhihu-paper-structure",
    name: "知乎 · 宏观布局",
    group: "写作",
    source: "丁霄汉 · 顶会论文写作建议（上）",
    sourceURL: "https://zhuanlan.zhihu.com/p/593195527",
    required: true,
    files: ["skills/zhihu-paper-structure/SKILL.md", "skills/zhihu-paper-structure/references/argument-to-revision.md", "skills/zhihu-paper-structure/references/narrative-design.md", "skills/zhihu-paper-structure/references/section-alignment.md", "skills/zhihu-paper-structure/references/structure-worksheet.md", "skills/zhihu-paper-structure/references/provenance.json"],
    description: "最终方案先行、贡献归属明确，让引言、方法概览与证据相互呼应。",
  },
  {
    id: "zhihu-paper-readability",
    name: "知乎 · 微观可读性",
    group: "写作",
    source: "丁霄汉 · 顶会论文写作建议（下）",
    sourceURL: "https://zhuanlan.zhihu.com/p/639732057",
    required: true,
    files: ["skills/zhihu-paper-readability/SKILL.md", "skills/zhihu-paper-readability/references/terminology-and-voice.md", "skills/zhihu-paper-readability/references/local-repair-protocol.md", "skills/zhihu-paper-readability/references/paragraph-diagnostics.md", "skills/zhihu-paper-readability/references/author-style.md", "skills/zhihu-paper-readability/references/passage-audit.md", "skills/zhihu-paper-readability/references/provenance.json"],
    description: "逐段检查逻辑强度、证据边界、理解成本与信息密度，不增加拗口表达。",
  },
  {
    id: "review",
    name: "十维审稿",
    group: "科学性",
    source: "AI-paper-reviewer",
    requires: ["paper-rebuttal"],
    files: ["vendor/AI-paper-reviewer/prompts/01_full_paper_audit.md", "skills/reviewer-workflow.md", "skills/modules/review.md"],
    description: "移植审稿台四视角：贡献证据、实验、逻辑与反驳复核，结合十维检查。",
  },
  {
    id: "paper-rebuttal",
    name: "知乎 · Rebuttal 与审稿回应",
    group: "答辩",
    source: "丁霄汉 · Rebuttal 经验",
    sourceURL: "https://zhuanlan.zhihu.com/p/602024489",
    files: ["skills/paper-rebuttal/SKILL.md", "skills/paper-rebuttal/references/counterevidence-defense.md", "skills/paper-rebuttal/references/response-worksheet.md", "skills/paper-rebuttal/references/revision-ledger.md", "skills/paper-rebuttal/references/provenance.json"],
    description: "按证据回应、区分误解与有效批评，明确改动状态；模拟审稿时核验作者可能的合理反驳。",
  },
  {
    id: "claims",
    name: "论断与证据",
    group: "科学性",
    source: "paper-pre-submission-review",
    files: [
      "vendor/paper-pre-submission-review/references/scientific-review.md",
      "skills/modules/claims.md",
    ],
    description: "核对论断范围、基线公平性、消融与数字一致性。",
  },
  {
    id: "citations",
    name: "引用核查",
    group: "完整性",
    source: "paper-pre-submission-review",
    files: ["vendor/paper-pre-submission-review/references/citations.md", "skills/modules/citations.md"],
    description: "核对引用键、归属与证据；外部文献身份标记待核验。",
  },
  {
    id: "math",
    name: "数学与符号",
    group: "完整性",
    source: "AI-paper-reviewer",
    files: ["vendor/AI-paper-reviewer/prompts/10_math_notation_check.md", "skills/modules/math.md"],
    description: "检查符号定义、维度、公式引用及跨章节一致性。",
  },
  {
    id: "blind",
    name: "双盲与复现",
    group: "投稿",
    source: "AI-paper-reviewer",
    files: [
      "vendor/AI-paper-reviewer/prompts/08_double_blind_check.md",
      "vendor/AI-paper-reviewer/prompts/13_repro_checklist.md",
      "skills/modules/blind.md",
    ],
    description: "检查身份线索、随机种子、数据划分和复现配置。",
  },
  {
    id: "venue",
    name: "投稿规则",
    group: "投稿",
    source: "paper-pre-submission-review",
    files: ["skills/modules/venue.md"],
    description: "按目标年份与 track 检查；没有官方材料时不判定通过。",
  },
  {
    id: "latex",
    name: "LaTeX 终检",
    group: "投稿",
    source: "paper-pre-submission-review",
    files: ["vendor/paper-pre-submission-review/references/writing-and-pdf.md", "skills/modules/latex.md"],
    description: "检查交叉引用、图表说明与编译日志；不冒充视觉终检。",
  },
];

export const figureSkillIds=skills.filter(s=>s.group==="绘图").map(s=>s.id);
export const defaultSkillIds=skills.filter(s=>s.default!==false).map(s=>s.id);
export const coreSkillIds=["writing","review","claims","citations","math","blind","venue","latex"];

export function effectiveSkillIds(ids) {
  if (!Array.isArray(ids) || ids.some((id) => !skills.some((s) => s.id === id)))
    throw new Error("未知 skill");
  const selected=new Set([...ids,...skills.filter(s=>s.required).map(s=>s.id)]);
  for(const id of selected) {
    const skill=skills.find(s=>s.id===id);
    if(!skill)throw new Error("未知 skill 依赖");
    for(const dependency of skill.requires||[])selected.add(dependency);
  }
  return skills.filter(s => selected.has(s.id)).map(s => s.id);
}

export async function skillManifest(ids) {
  const selected = effectiveSkillIds(ids);
  const files = [];
  const seen=new Set();
  for (const skill of skills.filter(s => selected.includes(s.id))) {
    for (const file of skill.files)if(!seen.has(file)){seen.add(file);files.push({file, sha256:createHash("sha256").update(await readFile(path.join(root,file))).digest("hex")});}
  }
  return {ids:selected,definitions:skills.filter(s=>selected.includes(s.id)).map(({id,name,source,sourceURL,required,requires,files})=>({id,name,source,sourceURL,required:Boolean(required),requires:requires||[],files})), moduleContracts:JSON.parse(await readFile(path.join(root,"skills/modules/provenance.json"),"utf8")), writingAIpaper:JSON.parse(await readFile(path.join(root,"skills/writing-ai-paper/references/provenance.json"),"utf8")), ...(selected.includes("paper-rebuttal")?{rebuttal:JSON.parse(await readFile(path.join(root,"skills/paper-rebuttal/references/provenance.json"),"utf8"))}:{}), files};
}

export async function skillPrompt(ids) {
  const selected = effectiveSkillIds(ids);
  const sections = [];
  const seen=new Set();
  for (const skill of skills.filter((s) => selected.includes(s.id))) {
    const contents = [];
    for (const file of skill.files)if(!seen.has(file)){
      seen.add(file);contents.push(await readFile(path.join(root, file), "utf8"));
    }
    sections.push(`## ${skill.name}\n${contents.join("\n")}`);
  }
  return sections.join("\n\n");
}
