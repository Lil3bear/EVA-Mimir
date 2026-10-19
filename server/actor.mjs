import {createHmac,timingSafeEqual} from "node:crypto";
export function actorHeader(actor,method,url,secret) {
  if(!actor || !secret)return {};
  const value=Buffer.from(JSON.stringify({actor,method,url,time:Date.now()})).toString("base64url");
  return {"x-workspace-actor":`${value}.${createHmac("sha256",secret).update(value).digest("hex")}`};
}
export function verifiedActor(header,method,url,secret) {
  if(typeof header!=="string" || !secret)return null;
  const [value,sig,...rest]=header.split(".");
  if(rest.length || !/^[a-f0-9]{64}$/.test(sig||"") || !timingSafeEqual(Buffer.from(sig,"hex"),createHmac("sha256",secret).update(value).digest()))return null;
  try {
    const data=JSON.parse(Buffer.from(value,"base64url").toString());
    if(data.method!==method || data.url!==url || !Number.isFinite(data.time) || Math.abs(Date.now()-data.time)>60000 || !/^[a-f0-9]{32}$/.test(data.actor?.id) || typeof data.actor?.name!=="string" || data.actor.name.length>40)return null;
    return {id:data.actor.id,name:data.actor.name};
  } catch {return null;}
}
