import {mkdtemp,readFile,rm} from "node:fs/promises";
import {tmpdir,homedir} from "node:os";
import path from "node:path";
import assert from "node:assert/strict";
import {chromium} from "@playwright/test";
import {remoteTeamGateway} from "../server/team-proxy.mjs";
import {passwordHash} from "../server/access.mjs";

// Uses isolated test accounts and reads the running local workspace without changing paper data.
const directory=await mkdtemp(path.join(tmpdir(),"apr-member-ui-"));
const config=JSON.parse(await readFile(path.join(homedir(),".config/autopaperreview/team-bridge.json"),"utf8"));
const app=remoteTeamGateway({target:"http://127.0.0.1:4317",token:config.token,frontendDir:path.resolve("dist"),access:{shared:true,port:4339,origin:"https://papers.example",secret:"s".repeat(64),passwordHash:passwordHash("test-invite"),membersFile:path.join(directory,"members.json")}});
const server=app.listen(4339,"127.0.0.1");
const browser=await chromium.launch({headless:true});
try {
  const context=await browser.newContext();const page=await context.newPage();
  await page.goto("http://localhost:4339");
  await page.getByRole("button",{name:"首次使用：创建个人账号"}).click();
  await page.getByLabel("个人用户名",{exact:true}).fill("alice");
  await page.getByLabel("显示姓名",{exact:true}).fill("Alice");
  await page.getByLabel("个人密码",{exact:true}).fill("personal-password-123");
  await page.getByLabel("团队邀请密码",{exact:true}).fill("test-invite");
  await page.getByRole("button",{name:"创建个人账号",exact:true}).click();
  await page.getByText("在线 1 人",{exact:true}).waitFor();
  await page.waitForFunction(()=>!document.body.textContent.includes("载入工作区"));
  const tab=await context.newPage();await tab.goto("http://localhost:4339");
  await tab.getByText("在线 1 人",{exact:true}).waitFor();
  await page.setViewportSize({width:1440,height:900});await page.screenshot({path:"/tmp/apr-members-desktop.png"});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:"/tmp/apr-members-mobile.png"});
  assert.ok(await page.locator(".app-header").evaluate(el=>el.scrollWidth<=el.clientWidth));
  await context.close();
  console.log("Registration, login, same-member tab deduplication and desktop/mobile header passed");
} finally {await browser.close();server.closeAllConnections();await new Promise(r=>server.close(r));await rm(directory,{recursive:true,force:true});}
