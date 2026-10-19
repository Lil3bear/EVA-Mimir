import { createHmac, randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

export function passwordHash(password, salt = randomBytes(16).toString("hex")) {
  return `${salt}:${scryptSync(password,salt,32).toString("hex")}`;
}
export function installAccess(app, options = {}) {
  const shared = options.shared || false;
  const origin = options.origin ? new URL(options.origin).origin : null;
  if (shared && (!origin?.startsWith("https:") || !/^[a-f0-9]{32}:[a-f0-9]{64}$/.test(options.passwordHash || "") || (options.secret || "").length < 32)) throw new Error("共享部署必须配置 HTTPS PUBLIC_ORIGIN、TEAM_PASSWORD_HASH 与 SESSION_SECRET");
  const validOrigins = new Set([`http://localhost:${options.port}`,`http://127.0.0.1:${options.port}`,...(origin ? [origin] : [])]);
  const hosts = new Set([...validOrigins].map(o=>new URL(o).host));
  const secure = origin?.startsWith("https:");
  const signature = value => createHmac("sha256",options.secret).update(value).digest("hex");
  function authenticated(req) {
    if (!shared) return true;
    const cookie = (req.headers.cookie || "").split(";").map(v=>v.trim()).find(v=>v.startsWith("autopaperreview_session="))?.split("=")[1];
    if (!cookie || !/^\d+\.[a-f0-9]{64}$/.test(cookie)) return false;
    const [time,sig] = cookie.split(".");
    return Number(time) > Date.now() && Number(time) < Date.now()+13*3600000 && timingSafeEqual(Buffer.from(sig,"hex"),Buffer.from(signature(time),"hex"));
  }
  app.use((req,res,next)=>{
    if (!hosts.has(req.headers.host || "")) return res.status(403).json({error:"访问地址未授权"});
    if (req.headers.origin && !validOrigins.has(req.headers.origin)) return res.status(403).json({error:"拒绝跨域访问"});
    res.setHeader("X-Content-Type-Options","nosniff");
    res.setHeader("X-Frame-Options","DENY");
    res.setHeader("Referrer-Policy","no-referrer");
    if (req.path.startsWith("/api/")) res.setHeader("Cache-Control","no-store");
    next();
  });
  app.get("/api/session",(req,res)=>res.json({shared,authenticated:authenticated(req)}));
  let attempts = 0, reset = 0;
  const cookieOptions = `Path=/; HttpOnly; SameSite=Strict${secure ? "; Secure" : ""}`;
  app.post("/api/session",(req,res)=>{
    if (!shared) return res.json({authenticated:true});
    if (Date.now() > reset) {attempts = 0; reset = Date.now()+60000;}
    if (++attempts > 10) return res.status(429).json({error:"登录尝试过多，请一分钟后重试"});
    const password = req.body?.password;
    if (typeof password !== "string" || password.length > 1024 || typeof req.body?.username !== "string") return res.status(400).json({error:"请输入用户名和密码"});
    const [salt,expected] = options.passwordHash.split(":");
    const actual = scryptSync(password,salt,32);
    if (req.body.username !== (options.username || "team") || !/^[a-f0-9]{64}$/.test(expected || "") || !timingSafeEqual(actual,Buffer.from(expected,"hex"))) return res.status(401).json({error:"用户名或密码错误"});
    const time = String(Date.now()+12*3600000);
    res.setHeader("Set-Cookie",`autopaperreview_session=${time}.${signature(time)}; Max-Age=43200; ${cookieOptions}`);
    res.json({authenticated:true});
  });
  app.post("/api/logout",(req,res)=>{
    res.setHeader("Set-Cookie",`autopaperreview_session=; Max-Age=0; ${cookieOptions}`);
    res.json({authenticated:false});
  });
  app.use("/api",(req,res,next)=>authenticated(req) ? next() : res.status(401).json({error:"请先登录团队工作区"}));
}
