import { createHmac, randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import {existsSync, readFileSync, mkdirSync, writeFileSync, renameSync} from "node:fs";
import path from "node:path";

export function passwordHash(password, salt = randomBytes(16).toString("hex")) {
  return `${salt}:${scryptSync(password,salt,32).toString("hex")}`;
}
export function installAccess(app, options = {}) {
  const members = options.membersFile && existsSync(options.membersFile) ? JSON.parse(readFileSync(options.membersFile,"utf8")) : {};
  const presence = new Map();
  const publicMember = m => ({id:m.id, name:m.name});
  const matches = (password, hash) => {
    if(typeof password!=="string" || password.length>1024 || !/^[a-f0-9]{32}:[a-f0-9]{64}$/.test(hash||""))return false;
    const [salt,value]=hash.split(":");
    return timingSafeEqual(scryptSync(password,salt,32),Buffer.from(value,"hex"));
  };
  const shared = options.shared || false;
  const origin = options.origin ? new URL(options.origin).origin : null;
  if (shared && (!origin?.startsWith("https:") || !/^[a-f0-9]{32}:[a-f0-9]{64}$/.test(options.passwordHash || "") || (options.secret || "").length < 32)) throw new Error("共享部署必须配置 HTTPS PUBLIC_ORIGIN、TEAM_PASSWORD_HASH 与 SESSION_SECRET");
  const validOrigins = new Set([`http://localhost:${options.port}`,`http://127.0.0.1:${options.port}`,...(origin ? [origin] : [])]);
  const hosts = new Set([...validOrigins].map(o=>new URL(o).host));
  const secure = origin?.startsWith("https:");
  const signature = value => createHmac("sha256",options.secret).update(value).digest("hex");
  function authenticated(req) {
    if (!shared) {req.actor={id:"local",name:"本机使用者"};return true;}
    const cookie = (req.headers.cookie || "").split(";").map(v=>v.trim()).find(v=>v.startsWith("autopaperreview_session="))?.split("=")[1];
    if(cookie?.startsWith("v2.")) {
      const [,payload,sig,...extra]=cookie.split(".");
      if(extra.length || !/^[a-f0-9]{64}$/.test(sig||"") || !timingSafeEqual(Buffer.from(sig,"hex"),Buffer.from(signature(payload),"hex")))return false;
      try {
        const session=JSON.parse(Buffer.from(payload,"base64url").toString());
        const member=Object.values(members).find(m=>m.id===session.id);
        if(!member || session.expires<=Date.now() || session.expires>Date.now()+13*3600000)return false;
        req.actor=publicMember(member);return true;
      } catch {return false;}
    }
    if (options.membersFile || !cookie || !/^\d+\.[a-f0-9]{64}$/.test(cookie)) return false;
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
  app.get("/api/session",(req,res)=>res.json({shared,authenticated:authenticated(req),member:req.actor,memberAccounts:Boolean(options.membersFile)}));
  let attempts = 0, reset = 0;
  const cookieOptions = `Path=/; HttpOnly; SameSite=Strict${secure ? "; Secure" : ""}`;
  app.post("/api/session",(req,res)=>{
    if (!shared) return res.json({authenticated:true});
    if (Date.now() > reset) {attempts = 0; reset = Date.now()+60000;}
    if (++attempts > 10) return res.status(429).json({error:"登录尝试过多，请一分钟后重试"});
    if(options.membersFile) {
      const {username,password,invitePassword,displayName,register}=req.body||{};
      if(typeof username!=="string" || !/^[a-zA-Z0-9_][a-zA-Z0-9_.-]{2,39}$/.test(username) || username.toLowerCase()===(options.username||"team").toLowerCase())return res.status(400).json({error:"请使用个人用户名（3–40 位字母、数字或下划线），不要使用 team"});
      const key=username.toLowerCase();
      if(["__proto__","constructor","prototype"].includes(key))return res.status(400).json({error:"请选择其他用户名"});
      if(register) {
        if(!matches(invitePassword,options.passwordHash))return res.status(401).json({error:"团队邀请密码不正确"});
        if(Object.hasOwn(members,key))return res.status(409).json({error:"用户名已被注册"});
        if(typeof password!=="string" || password.length<12 || password.length>1024 || typeof displayName!=="string" || !displayName.trim() || displayName.trim().length>40)return res.status(400).json({error:"请输入显示姓名和至少 12 位个人密码"});
        const member={id:randomBytes(16).toString("hex"),name:displayName.trim(),passwordHash:passwordHash(password)};
        const next={...members,[key]:member};
        mkdirSync(path.dirname(options.membersFile),{recursive:true,mode:0o700});
        writeFileSync(options.membersFile+".tmp",JSON.stringify(next),{mode:0o600});
        renameSync(options.membersFile+".tmp",options.membersFile);
        members[key]=member;
      }
      const member=Object.hasOwn(members,key)?members[key]:null;
      if(!member || !matches(password,member.passwordHash))return res.status(401).json({error:"用户名或密码错误"});
      const payload=Buffer.from(JSON.stringify({id:member.id,expires:Date.now()+12*3600000})).toString("base64url");
      res.setHeader("Set-Cookie",`autopaperreview_session=v2.${payload}.${signature(payload)}; Max-Age=43200; ${cookieOptions}`);
      return res.json({authenticated:true,shared:true,member:publicMember(member),memberAccounts:true});
    }
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
    if(authenticated(req)&&req.actor)presence.delete(req.actor.id);
    res.setHeader("Set-Cookie",`autopaperreview_session=; Max-Age=0; ${cookieOptions}`);
    res.json({authenticated:false});
  });
  app.use("/api",(req,res,next)=>authenticated(req) ? next() : res.status(401).json({error:"请先登录团队工作区"}));
  app.post("/api/session/presence",(req,res)=>{
    if(req.actor)presence.set(req.actor.id,{...req.actor,seen:Date.now()});
    for(const [id,m] of presence)if(Date.now()-m.seen>75000)presence.delete(id);
    res.json({members:[...presence.values()].map(publicMember),count:presence.size});
  });
}
