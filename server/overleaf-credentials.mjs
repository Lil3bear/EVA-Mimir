import {createCipheriv, createDecipheriv, randomBytes, randomUUID} from "node:crypto";
import {mkdir, readFile, writeFile, rename, rm, chmod} from "node:fs/promises";
import path from "node:path";

// Keep credentials outside project data, exports and source Git history.
export function overleafCredentials(directory) {
  let initializing;
  const file = id => {
    if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(id)) throw Error("Invalid project ID");
    return path.join(directory, `${id}.json`);
  };
  async function key(create = false) {
    const target = path.join(directory, "key");
    if (create) {
      initializing ||= (async()=>{
        await mkdir(directory, {recursive:true, mode:0o700});
        await chmod(directory, 0o700);
        await writeFile(target, randomBytes(32), {flag:"wx", mode:0o600}).catch(error => {if(error.code !== "EEXIST") throw error;});
      })().catch(error=>{initializing=undefined;throw error;});
    }
    if(initializing) await initializing;
    const bytes = await readFile(target);
    if (bytes.length !== 32) throw Error("Invalid credential encryption key");
    return bytes;
  }
  return {
    async get(id, url) {
      const record = await readFile(file(id), "utf8").then(JSON.parse).catch(error => {if(error.code === "ENOENT") return null; throw error;});
      if (!record) return undefined;
      try {
        const decipher = createDecipheriv("aes-256-gcm", await key(), Buffer.from(record.iv,"base64"));
        decipher.setAAD(Buffer.from(id));
        decipher.setAuthTag(Buffer.from(record.tag,"base64"));
        const saved = JSON.parse(Buffer.concat([decipher.update(Buffer.from(record.data,"base64")), decipher.final()]).toString("utf8"));
        return saved.url === url ? saved.token : undefined;
      } catch {
        throw Error("Overleaf 已保存凭据无法解密，请重新认证；未推送任何修改");
      }
    },
    async set(id, url, token) {
      const target = file(id);
      const iv = randomBytes(12), cipher = createCipheriv("aes-256-gcm", await key(true), iv);
      cipher.setAAD(Buffer.from(id));
      const data = Buffer.concat([cipher.update(JSON.stringify({url,token}),"utf8"),cipher.final()]);
      const temporary = `${target}.${randomUUID()}.tmp`;
      try {
        await writeFile(temporary, JSON.stringify({iv:iv.toString("base64"),tag:cipher.getAuthTag().toString("base64"),data:data.toString("base64")}), {flag:"wx",mode:0o600});
        await rename(temporary, target);
      } finally {await rm(temporary,{force:true});}
    },
    async delete(id) {await rm(file(id),{force:true});},
  };
}
