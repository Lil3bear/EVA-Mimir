import http from "node:http";
import {timingSafeEqual} from "node:crypto";
import {isIP} from "node:net";
import path from "node:path";
import {createGzip} from "node:zlib";
import express from "express";
import {installAccess} from "./access.mjs";
import {revisionPDFCache} from "./pdf-cache.mjs";
import {PullQueue,installPullWorker,installPullBrowser} from "./pull-queue.mjs";

function targetURL(value,privateHost) {
  const url = new URL(value);
  const pinnedVPN=isIP(privateHost||"")===4 && /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(privateHost) && url.hostname === privateHost && url.port === "4320";
  if (url.protocol !== "http:" || !(["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)||pinnedVPN) || url.username || url.password || url.pathname !== "/" || url.search || url.hash)
    throw Error("Bridge target must be a fixed loopback HTTP origin");
  return url;
}
function checkToken(token) {
  if (!/^[a-f0-9]{64}$/.test(token || "")) throw Error("A private 256-bit bridge token is required");
}
function proxy(req, res, target, token, sharedHealth=false) {
  const headers = {...req.headers, host: target.host};
  for (const key of ["authorization", "cookie", "connection", "proxy-authorization", "upgrade", "transfer-encoding", "forwarded", "x-forwarded-host", "x-forwarded-for", "x-forwarded-proto", "x-team-bridge-token"])
    delete headers[key];
  // Only the authenticated gateway may cross this boundary; browser identities never reach native clients.
  if (headers.origin) headers.origin = target.origin;
  if (token) headers["x-team-bridge-token"] = token;
  const upstream = http.request({hostname:target.hostname, port:target.port, method:req.method, path:req.originalUrl, headers}, response => {
    if (sharedHealth && req.method === "GET" && req.originalUrl === "/api/health" && response.statusCode === 200) {
      let body="";
      response.setEncoding("utf8");response.on("data",chunk=>body+=chunk);
      response.on("end",()=>{
        try {res.json({...JSON.parse(body),shared:true,localExecution:true});}
        catch {res.status(502).json({error:"执行端状态响应无效"});}
      });
      response.on("error",()=>res.destroy());
      return;
    }
    const responseHeaders = {...response.headers};
    delete responseHeaders["set-cookie"];
    const compress = req.originalUrl!=="/api/health" && req.headers["accept-encoding"] && req.acceptsEncodings("gzip") &&
      !responseHeaders["content-encoding"] && /^application\/json/.test(responseHeaders["content-type"]||"") &&
      Number(responseHeaders["content-length"]||0)>1024;
    response.on("error",()=>res.destroy());
    if(compress) {
      delete responseHeaders["content-length"];
      responseHeaders["content-encoding"]="gzip";
      responseHeaders.vary=[responseHeaders.vary,"Accept-Encoding"].filter(Boolean).join(", ");
    }
    res.writeHead(response.statusCode, responseHeaders);
    if(compress) {
      const gzip=createGzip();gzip.on("error",()=>res.destroy());response.pipe(gzip).pipe(res);
    } else response.pipe(res);
  });
  upstream.setTimeout(120000, () => upstream.destroy(Error("upstream timeout")));
  upstream.on("error", () => {
    const readOnly = req.method === "GET" || req.method === "HEAD";
    if (!res.headersSent) res.status(503).json({
      code: readOnly ? "WORKSPACE_UNREACHABLE" : "WRITE_UNCONFIRMED",
      error: readOnly
        ? "团队服务器暂时无法连接工作区执行端，无法读取数据。这不是访问者电脑缺少配置；请联系管理员检查服务器与工作区之间的连接，稍后刷新。"
        : "团队服务器与工作区执行端连接中断；本次提交结果未确认，请勿重复提交，恢复连接后检查批注与修订日志。"
    });
    else res.destroy();
  });
  req.on("aborted", () => upstream.destroy());
  res.on("close", () => {if (!res.writableFinished) upstream.destroy();});
  req.pipe(upstream);
}
export function localTeamBridge({target, token, peers, deploymentBundle}) {
  checkToken(token);
  const destination = targetURL(target);
  const app = express();
  app.disable("x-powered-by");
  app.use((req,res) => {
    if (peers && !peers.includes(req.socket.remoteAddress)) return res.status(403).json({error:"执行端仅允许已配置的私有网络节点"});
    const supplied = req.headers["x-team-bridge-token"];
    if (typeof supplied !== "string" || supplied.length !== token.length || !timingSafeEqual(Buffer.from(supplied),Buffer.from(token)))
      return res.status(401).json({error:"执行端认证失败"});
    if(deploymentBundle && req.method==="GET" && req.originalUrl==="/__team-deployment-bundle")
      return res.sendFile(path.basename(deploymentBundle),{root:path.dirname(deploymentBundle)});
    proxy(req,res,destination);
  });
  return app;
}
export function remoteTeamGateway({target, token, access, privateHost, frontendDir, pdfCacheDir, queueDir}) {
  checkToken(token);
  const destination = targetURL(target,privateHost);
  if (!access?.shared) throw Error("The public gateway requires team authentication");
  const app = express();
  app.disable("x-powered-by");
  const queue=queueDir?new PullQueue(queueDir):null;
  if(queue)installPullWorker(app,queue,token);
  // Do not parse manuscript/ZIP bodies: they must stream byte-for-byte to the one workspace.
  app.use("/api/session", express.json({limit:"8kb"}));
  installAccess(app,access);
  if(queue)installPullBrowser(app,queue);
  if(pdfCacheDir&&!queue)app.use(revisionPDFCache({directory:pdfCacheDir,target:destination,token}));
  if(frontendDir) {
    app.use(express.static(frontendDir));
    app.get(/^\/(?!api(?:\/|$)).*/, (req,res)=>res.sendFile("index.html",{root:frontendDir}));
  }
  app.use((req,res) => proxy(req,res,destination,token,true));
  if(queue)app.use((error,req,res,next)=>{
    if(res.headersSent)return next(error);
    res.status(error.status||500).json({error:error.status?error.message:"队列存储失败，未确认接收；请联系管理员检查磁盘。"});
  });
  return app;
}
