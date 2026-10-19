import {mkdir,cp,writeFile} from "node:fs/promises";
import {homedir} from "node:os";
import path from "node:path";
import {execFileSync} from "node:child_process";

const home=homedir(),runtime=path.join(home,".local/share/autopaperreview");
for(const file of ["server/pull-worker.mjs","deploy/run-pull-worker.mjs"]) {
  await mkdir(path.dirname(path.join(runtime,file)),{recursive:true});
  await cp(file,path.join(runtime,file));
}
const label="com.autopaperreview.pull-worker",logs=path.join(home,".config/autopaperreview/logs");
await mkdir(logs,{recursive:true,mode:0o700});
const escape=s=>s.replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
const plist=path.join(home,"Library/LaunchAgents",label+".plist");
await writeFile(plist,`<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>Label</key><string>${label}</string><key>ProgramArguments</key><array><string>${escape(process.execPath)}</string><string>${escape(path.join(runtime,"deploy/run-pull-worker.mjs"))}</string></array><key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>15</integer><key>StandardOutPath</key><string>${escape(path.join(logs,"pull-worker.log"))}</string><key>StandardErrorPath</key><string>${escape(path.join(logs,"pull-worker.err"))}</string></dict></plist>`,{mode:0o600});
try{execFileSync("launchctl",["bootout",`gui/${process.getuid()}/${label}`],{stdio:"ignore"});}catch{}
for(let attempt=0;;attempt++) {
  try{execFileSync("launchctl",["bootstrap",`gui/${process.getuid()}`,plist],{stdio:"pipe"});break;}
  catch(error){if(attempt===9)throw error;await new Promise(resolve=>setTimeout(resolve,3000));}
}
console.log("Outbound executor installed; native credentials remain local.");
