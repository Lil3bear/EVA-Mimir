import {readFile} from "node:fs/promises";
import {homedir} from "node:os";
import path from "node:path";
import {localTeamBridge,remoteTeamGateway} from "../server/team-proxy.mjs";

const config = JSON.parse(await readFile(process.env.TEAM_BRIDGE_CONFIG || path.join(homedir(),".config/autopaperreview/team-bridge.json"),"utf8"));
const remote = process.argv.includes("--remote");
const app = remote ? remoteTeamGateway({target:config.remoteTarget,token:config.token,access:{...config.access,shared:true,membersFile:config.access.membersFile || path.join(process.env.TEAM_QUEUE_DIR || path.dirname(process.env.TEAM_BRIDGE_CONFIG || path.join(homedir(),".config/autopaperreview/team-bridge.json")),"members.json")},privateHost:config.bridgeHost,frontendDir:path.resolve("dist"),pdfCacheDir:process.env.TEAM_PDF_CACHE_DIR,queueDir:process.env.TEAM_QUEUE_DIR})
  : localTeamBridge({target:config.localTarget,token:config.token,peers:config.peers,deploymentBundle:config.deploymentBundle});
const server = app.listen(remote ? 4318 : 4320,remote?(process.env.TEAM_GATEWAY_BIND||"127.0.0.1"):config.bridgeHost,() => console.log(remote ? "Authenticated remote workspace gateway ready" : "Private local workspace bridge ready"));
for (const signal of ["SIGTERM","SIGINT"]) process.on(signal,() => server.close(() => process.exit(0)));
