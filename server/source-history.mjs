import {mkdir,rm,access} from "node:fs/promises";
import path from "node:path";
import {randomUUID} from "node:crypto";
import {git} from "./overleaf.mjs";
import {safePath} from "./core.mjs";

const revisionId=id=>{if(!/^[a-f0-9-]{36}$/.test(id))throw Error("无效的历史版本编号");return id;};
export async function recordSourceCommit(directory,revision,parent) {
  const repository=path.join(directory,"source-history.git"),ref=`refs/revisions/${revisionId(revision.id)}`;
  await mkdir(directory,{recursive:true});
  if(!await access(path.join(repository,"HEAD")).then(()=>true).catch(()=>false))await git(["init","--bare","--",repository]);
  const base=["--git-dir",repository];
  const existing=await git([...base,"rev-parse","--verify",ref]).then(b=>b.toString().trim()).catch(()=>null);
  if(existing){await git([...base,"update-ref","refs/heads/history",existing]);await git([...base,"symbolic-ref","HEAD","refs/heads/history"]);return existing;}
  const index=path.join(directory,`history-${randomUUID()}.index`);
  try {
    await git([...base,"read-tree","--empty"],{index});
    const entries=[];
    for(const [file,data] of Object.entries(revision.files)) {
      safePath(file);
      const hash=(await git([...base,"hash-object","-w","--stdin"],{input:Buffer.from(data,"base64")})).toString().trim();
      entries.push(`100644 ${hash}\t${file}\0`);
    }
    await git([...base,"update-index","-z","--index-info"],{index,input:entries.join("")});
    const tree=(await git([...base,"write-tree"],{index})).toString().trim();
    const metadata={revision:revision.id,parentRevision:revision.parent||null,time:revision.time,label:revision.label,main:revision.main,engine:revision.engine,provenance:revision.provenance||null,restoredFrom:revision.restoredFrom||null,initiatedBy:revision.initiatedBy||null};
    const commit=(await git([...base,"-c","user.name=Autopaperreview","-c","user.email=autopaperreview@localhost","commit-tree",tree,...(parent?["-p",parent]:[])],{input:`${revision.label}\n\n${JSON.stringify(metadata)}\n`})).toString().trim();
    await git([...base,"update-ref",ref,commit]);
    await git([...base,"update-ref","refs/heads/history",commit]);
    await git([...base,"symbolic-ref","HEAD","refs/heads/history"]);
    return commit;
  } finally {await rm(index,{force:true});}
}
export async function sourceCommitDiff(directory,id) {
  return (await git(["--git-dir",path.join(directory,"source-history.git"),"show","--format=fuller","--no-ext-diff","--no-textconv",`refs/revisions/${revisionId(id)}`,"--"])).toString("utf8");
}
