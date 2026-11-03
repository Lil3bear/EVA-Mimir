#!/usr/bin/env node
import {readFile, writeFile, mkdir, rm, symlink, stat, access} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const bundle = path.join(root, "dsh", "mimir");
const args = new Set(process.argv.slice(2));
const home = process.env.DSH_HOME || path.join(os.homedir(), ".dsh");
const profile = process.env.DSH_PROFILE || "desktop";
const profileDir = path.join(home, "profiles", profile);
const pkgFile = path.join(profileDir, "package.json");
const patchFile = path.join(bundle, "cordis.patch.yml");
const link = path.join(profileDir, "node_modules", "@local", "dsh-mimir");

const exists = async file => access(file).then(() => true, () => false);
if (!await exists(profileDir)) {
  console.error(`找不到 DSH profile：${profileDir}\n请先安装并至少打开一次 DeepSeek Harness。`);
  process.exit(1);
}
const pkg = JSON.parse(await readFile(pkgFile, "utf8"));
const uninstall = args.has("--uninstall");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
await copy(`${pkgFile}.bak-mimir-${stamp}`);

if (uninstall) {
  if (pkg.dependencies) delete pkg.dependencies["@local/dsh-mimir"];
  const bundles = pkg.dsh?.profile?.bundles;
  if (Array.isArray(bundles)) pkg.dsh.profile.bundles = bundles.filter(name => name !== "@local/dsh-mimir");
  await writeFile(pkgFile, JSON.stringify(pkg, null, 2) + "\n");
  await rm(link, {recursive: true, force: true});
  console.log("已移除 @local/dsh-mimir；论文数据未删除。重启 DSH 后生效。");
  process.exit(0);
}

// The bundle owns the app; keep every absolute path inside this extracted folder.
const patch = `# Installed by mimir-pi install.command
- insert:
    - id: dsh-mimir
      name: '@local/dsh-mimir'
      config:
        packageDir: "${root}"
    - id: dsh-mimir-skills
      name: '@deepseek-ai/dsh-skill-filesystem'
      config:
        providerName: mimir
        includeDefaultRoots: false
        customSkillDirs:
          - "${path.join(bundle, "skills")}"
          - "${path.join(root, "skills", "sections")}"
          - "${path.join(root, "skills")}"
`;
await writeFile(patchFile, patch, {mode: 0o600});

pkg.dependencies ||= {};
pkg.dependencies["@local/dsh-mimir"] = `file:${bundle}`;
pkg.dsh ||= {};
pkg.dsh.profile ||= {};
pkg.dsh.profile.bundles ||= [];
if (!pkg.dsh.profile.bundles.includes("@local/dsh-mimir")) pkg.dsh.profile.bundles.push("@local/dsh-mimir");
await writeFile(pkgFile, JSON.stringify(pkg, null, 2) + "\n");

await mkdir(path.dirname(link), {recursive: true});
await rm(link, {recursive: true, force: true});
await symlink(bundle, link, "dir");

const pdflatex = await new Promise(resolve => {
  import("node:child_process").then(({spawn}) => {
    const child = spawn("pdflatex", ["--version"], {stdio: "ignore"});
    child.on("error", () => resolve(false));
    child.on("close", code => resolve(code === 0));
  });
});
console.log(`已安装到 DSH profile：${profile}`);
console.log(`应用目录：${root}`);
console.log(pdflatex ? "LaTeX：已找到 pdflatex" : "LaTeX：未找到 pdflatex；编辑/审稿/翻译可用，编译 PDF 需要 MacTeX");
console.log("下一步：完全退出并重新打开 DeepSeek Harness，然后输入 /mimir。");

async function copy(target) {
  try { await writeFile(target, await readFile(pkgFile), {mode: 0o600}); } catch {}
}
