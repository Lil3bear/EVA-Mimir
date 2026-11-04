import {mkdir,writeFile} from "node:fs/promises";
import {homedir} from "node:os";
import path from "node:path";
import {randomBytes} from "node:crypto";
import {passwordHash} from "../server/access.mjs";

const origin=new URL(process.argv[2]||""),username=process.argv[3]||"team";
if(origin.protocol!=="https:"||origin.username||origin.password||origin.pathname!=="/"||origin.search||origin.hash)throw Error("Provide a plain HTTPS public origin");
const directory=process.env.TEAM_CONFIG_DIR||path.join(homedir(),".config/autopaperreview");
await mkdir(directory,{recursive:true,mode:0o700});
const password=randomBytes(24).toString("base64url");
const config={token:randomBytes(32).toString("hex"),localTarget:"http://127.0.0.1:4317",remoteTarget:"http://127.0.0.1:4320",bridgeHost:"127.0.0.1",access:{shared:true,origin:origin.origin,port:4318,username,passwordHash:passwordHash(password),secret:randomBytes(32).toString("hex")}};
await writeFile(path.join(directory,"team-bridge.json"),JSON.stringify(config,null,2),{flag:"wx",mode:0o600});
await writeFile(path.join(directory,"team-login.txt"),`Origin: ${origin.origin}\nUsername: ${username}\nPassword: ${password}\n`,{flag:"wx",mode:0o600});
console.log(`Private configuration created in ${directory}; read team-login.txt locally. Do not commit these files.`);
