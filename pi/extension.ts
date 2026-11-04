import type {ExtensionAPI} from "@earendil-works/pi-coding-agent";
import {execFile} from "node:child_process";
import {startWriting} from "./launch.mjs";

export default function mimir(pi: ExtensionAPI) {
  let service: Awaited<ReturnType<typeof startWriting>> | undefined;
  pi.registerCommand("mimir", {
    description: "Open the local DeepSeek writing workspace; optionally pass an Overleaf Git URL",
    handler: async (args, ctx) => {
      try {
        const input = args.trim() || (ctx.hasUI ? await ctx.ui.input("Overleaf Git URL (optional)", "https://git.overleaf.com/PROJECT_ID") : "");
        if (input === undefined) return;
        if (input) {
          const url = new URL(input);
          if (url.protocol !== "https:" || url.hostname !== "git.overleaf.com" || url.port || url.password ||
            (url.username && url.username !== "git") || url.search || url.hash || !/^\/[a-zA-Z0-9]+$/.test(url.pathname))
            throw new Error("Use a credential-free Overleaf Git URL; enter tokens only in the local browser form");
        }
        if (!service?.child) service = await startWriting({onExit: () => {service = undefined;}});
        const link = service.url + (input ? "/?overleaf=" + encodeURIComponent(input) : "");
        pi.appendEntry("mimir-workspace", {url: service.url, model: service.model, dataDirectory: service.directory});
        ctx.ui.notify(link, "info");
        if (process.platform === "darwin") execFile("open", [link], error => {
          if (error) ctx.ui.notify("Open this link in your browser: " + link, "warning");
        });
      } catch (error) {
        ctx.ui.notify(error instanceof Error ? error.message : "Writing workspace failed", "error");
      }
    },
  });
  pi.on("session_shutdown", async () => {
    const child = service?.child;
    service = undefined;
    if (child && child.exitCode === null && child.signalCode === null) {
      await new Promise<void>(resolve => {
        const timer = setTimeout(() => {child.kill("SIGKILL"); resolve();}, 3000);
        child.once("exit", () => {clearTimeout(timer); resolve();});
        child.kill("SIGTERM");
      });
    }
  });
}
