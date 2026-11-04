import {spawn} from "node:child_process";
import {mkdir, readFile, writeFile, rm} from "node:fs/promises";
import {randomUUID} from "node:crypto";
import {createServer} from "node:net";
import {homedir} from "node:os";
import path from "node:path";
import {fileURLToPath, pathToFileURL} from "node:url";

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const dataRoot = path.join(homedir(), ".local/share/mimir-pi");

export async function deepseekConfig() {
  const file = path.join(homedir(), ".config/autopaperreview/deepseek-official.json");
  const saved = await readFile(file, "utf8").then(JSON.parse).catch(error => {
    if (error.code === "ENOENT") return {};
    throw new Error("DeepSeek configuration could not be read");
  });
  if (saved.baseURL && saved.baseURL !== "https://api.deepseek.com/v1")
    throw new Error("Only the official DeepSeek endpoint is allowed");
  const apiKey = saved.apiKey || process.env.DEEPSEEK_API_KEY;
  if (!apiKey) throw new Error("Configure DEEPSEEK_API_KEY locally first");
  return {apiKey, model: saved.model || "deepseek-flash"};
}


export async function dshBackendConfig() {
  const file = path.join(homedir(), ".config/autopaperreview/deepseek-official.json");
  const saved = await readFile(file, "utf8").then(JSON.parse).catch(error => {
    if (error.code === "ENOENT") return {};
    throw new Error("本地模型配置无法读取");
  });
  const gemini = await readFile(path.join(homedir(), ".config/autopaperreview/gemini.json"), "utf8").then(JSON.parse).catch(() => ({}));
  // Model choices only. Authentication is owned by the local Harness / Gemini.
  return {model: saved.model || "deepseek-flash", gemini: Boolean(gemini.apiKey), geminiModel: gemini.model || "gemini-3.5-flash"};
}

async function freePort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

export async function startWriting({directory = dataRoot, onExit = () => {}, execPath = process.execPath, env: extraEnv = null} = {}) {
  const {model, gemini, geminiModel} = await dshBackendConfig();
  await mkdir(directory,{recursive:true,mode:0o700});
  const lock = path.join(directory,"writer.json"), instance = randomUUID();
  for (let attempt=0;attempt<2;attempt++) {
    try {await writeFile(lock,JSON.stringify({pid:process.pid,instance}),{flag:"wx",mode:0o600});break;}
    catch (error) {
      if (error.code!=="EEXIST") throw error;
      const running = await readFile(lock,"utf8").then(JSON.parse);
      let alive = true;
      try {process.kill(running.pid,0);} catch (error) {if(error.code==="ESRCH")alive=false;else throw error;}
      if (!alive && attempt===0) {await rm(lock);continue;}
      if (running.url && /^http:\/\/127\.0\.0\.1:\d+$/.test(running.url)) {
        const health = await fetch(running.url+"/api/health",{signal:AbortSignal.timeout(3000)}).then(r=>r.json()).catch(()=>null);
        if (health?.mimirInstance===running.instance)
          return {child:null,url:running.url,model:running.model,directory,reused:true};
      }
      throw new Error("The writing workspace is starting or unavailable; wait before opening another writer");
    }
  }
  let releasePromise;
  const release = () => releasePromise ||= rm(lock,{force:true});
  try {
  const agent = path.join(directory, "pi-agent");
  await mkdir(agent, {recursive: true, mode: 0o700});
  await mkdir(path.join(directory, "pi-sessions"), {recursive: true, mode: 0o700});
  await writeFile(path.join(agent, "models.json"), JSON.stringify({providers: {deepseek: {
    baseUrl: "https://api.deepseek.com/v1", apiKey: "$DEEPSEEK_API_KEY",
    modelOverrides: {[model]: {maxTokens: 8192}},
  }}}), {mode: 0o600});
  await writeFile(path.join(agent, "settings.json"), JSON.stringify({
    defaultProvider: "deepseek", defaultModel: model, defaultThinkingLevel: "off",
    compaction: {enabled: false}, retry: {enabled: false},
  }), {mode: 0o600});
  const port = await freePort();
  const env = {...process.env, ...(extraEnv || {})};
  for (const key of ["REVISION_REVIEWER", "REVISION_COWRITER_MODEL", "REVISION_COWRITER_AUTH",
    "REVISION_CROSSCHECK_MODEL", "REVISION_TEAM_MODE", "DEFAULT_PROJECT_ID", "PUBLIC_ORIGIN",
    "SHARED_MODE", "TEAM_BRIDGE_CONFIG"]) delete env[key];
  Object.assign(env, {
    PORT: String(port), BIND_HOST: "127.0.0.1", DATA_DIR: directory, NODE_ENV: "production",
    SETTINGS_LOCKED: "1", AI_PROVIDER: "dsh", OPENAI_BASE_URL: "https://api.deepseek.com/v1",
    OPENAI_MODEL: model,
    AI_API_FORMAT: "chat-json", REVISION_TRANSPORT: "dsh-cli", LOCAL_REVISION_ONLY: "1",
    MIMIR_GEMINI_COWRITER: gemini ? "1" : "0", GEMINI_MODEL: geminiModel,
    ARCHIVE_APPLIED_COMMENTS: "0", TRANSLATION_MODEL: process.env.TRANSLATION_MODEL || model, PI_CODING_AGENT_DIR: agent,
    MIMIR_PI_SESSION_DIR: path.join(directory, "pi-sessions"),
    OVERLEAF_CREDENTIAL_DIR: path.join(directory, "credentials/overleaf"),
    TEAM_BRIDGE_CONFIG:path.join(directory,"no-team-bridge.json"), MIMIR_INSTANCE:instance,
  });
  const child = spawn(execPath, [path.join(root, "server/index.mjs")], {
    cwd: root, env, stdio: ["ignore", "pipe", "pipe"],
  });
  let errors = "";
  child.stderr.on("data", data => { errors = (errors + data).slice(-4000); });
  const released = () => {release().catch(()=>{});onExit();};
  child.once("exit", released);
  child.once("error", released);
  const url = `http://127.0.0.1:${port}`;
  await writeFile(lock,JSON.stringify({pid:child.pid,instance,url,model}),{mode:0o600});
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {child.kill(); reject(new Error("Writing service startup timed out"));}, 15000);
    const fail = () => {clearTimeout(timer); reject(new Error("Writing service failed to start: " + errors));};
    child.once("error", fail);
    child.once("exit", fail);
    child.stdout.on("data", data => {
      if (String(data).includes("Autopaperreview:")) {
        clearTimeout(timer); child.removeListener("exit", fail); child.removeListener("error", fail); resolve();
      }
    });
  });
  return {child, url, model, directory,reused:false};
  } catch (error) {await release();throw error;}
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const service = await startWriting();
  console.log(service.url);
  if (!service.child) process.exit();
  const stop = () => service.child.kill("SIGTERM");
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  service.child.once("exit", () => process.exit());
}
