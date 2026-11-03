import path from "node:path";
import {fileURLToPath, pathToFileURL} from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const defaultPackageDir = path.resolve(here, "..", "..");

const OVERLEAF_GIT = /^https?:\/\/(?:git@)?git\.overleaf\.com\/([A-Za-z0-9]+)\/?$/;
const OVERLEAF_PROJECT = /^https?:\/\/(?:www\.)?overleaf\.com\/project\/([A-Za-z0-9]+)(?:\/.*)?$/;

/** Accept the clone URL, the git URL, or the web project URL; never a token. */
function overleafProjectUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return {url: null};
  const match = OVERLEAF_GIT.exec(raw) || OVERLEAF_PROJECT.exec(raw);
  if (!match) return {
    error: "只接受 Overleaf 项目地址，例如 https://git.overleaf.com/<project-id> 或 https://www.overleaf.com/project/<project-id>；Git token 请在打开后的 Overleaf 表单里填写，不要放进命令。",
  };
  return {url: `https://git.overleaf.com/${match[1]}`};
}

export const name = "dsh-mimir";
export const inject = ["commands"];

/**
 * Host half of the DSH bundle.
 *
 * The workspace stays a separate local service. This plugin only owns its
 * lifecycle: start on first use, reuse a running writer, and stop the child it
 * created when the plugin is disposed. The browser page remains reachable
 * through DSH's Sidebar Browser or the normal browser.
 */
export function apply(ctx, config = {}) {
  const packageDir = path.resolve(config.packageDir || defaultPackageDir);
  let service = null;
  let starting = null;

  async function ensure() {
    if (service?.child && service.child.exitCode !== null) service = null;
    if (service) return service;
    if (!starting) {
      starting = (async () => {
        const launcher = path.join(packageDir, "pi", "launch.mjs");
        const {startWriting} = await import(pathToFileURL(launcher).href);
        // The DSH host is Electron. ELECTRON_RUN_AS_NODE lets the same binary
        // boot mimir-pi's Express server as a plain Node process.
        const env = process.versions.electron ? {ELECTRON_RUN_AS_NODE: "1"} : null;
        service = await startWriting({execPath: process.execPath, env});
        return service;
      })().finally(() => {
        starting = null;
      });
    }
    return starting;
  }

  ctx.effect(() => () => {
    const child = service?.child;
    service = null;
    if (child && child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
  });

  ctx.commands.register({
    name: "mimir",
    description: "启动并打开本机 mimir-pi 论文工作区",
    input: {hint: "[Overleaf Git 地址，可选]"},
    recordInput: false,
    handler: async ({rawInput} = {}) => {
      const parsed = overleafProjectUrl(rawInput);
      if (parsed.error) return {kind: "error", text: parsed.error};
      try {
        const writable = await ensure();
        const url = parsed.url ? `${writable.url}/?overleaf=${encodeURIComponent(parsed.url)}` : writable.url;
        return {
          kind: "success",
          text: `Mimir 已就绪：${url}\n在 DSH 右侧栏打开：按 ⌘T 后粘贴地址，或把链接偏好设为「应用内侧边栏」再点链接。`,
        };
      } catch (error) {
        return {kind: "error", text: `Mimir 启动失败：${error?.message || String(error)}`};
      }
    },
  });
}
