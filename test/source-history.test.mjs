import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {randomUUID} from "node:crypto";
import {recordSourceCommit,sourceCommitDiff} from "../server/source-history.mjs";
import {git} from "../server/overleaf.mjs";
test("real Git commits preserve source, binary assets, parents and model provenance without remotes",async()=>{
  const dir=await mkdtemp(path.join(tmpdir(),"autopaper-git-"));
  try {
    const files={'main.tex':Buffer.from('Before.\n').toString('base64'),'fig/a.pdf':Buffer.from([0,255,1,2]).toString('base64')};
    const first={id:randomUUID(),time:new Date().toISOString(),label:'import',files,main:'main.tex',engine:'pdflatex'};
    const a=await recordSourceCommit(dir,first);
    assert.equal(await recordSourceCommit(dir,first),a);
    const second={...first,id:randomUUID(),parent:first.id,label:'AI revision',provenance:{kind:'ai',model:'fixture-editor',provider:'openai',proposalId:randomUUID()},files:{...files,'main.tex':Buffer.from('After.\n').toString('base64')}};
    const b=await recordSourceCommit(dir,second,a),base=['--git-dir',path.join(dir,'source-history.git')];
    assert.equal((await git([...base,'rev-parse',`${b}^`])).toString().trim(),a);
    assert.equal((await git([...base,'show',`${b}:fig/a.pdf`])).toString('base64'),files['fig/a.pdf']);
    const diff=await sourceCommitDiff(dir,second.id);assert.match(diff,/fixture-editor/);assert.match(diff,/-Before\./);assert.match(diff,/\+After\./);
    assert.equal((await git([...base,'remote'])).toString(),'');
    const restored={...first,id:randomUUID(),parent:second.id,label:'restore',restoredFrom:first.id};
    const c=await recordSourceCommit(dir,restored,b);
    assert.equal((await git([...base,'show',`${c}:main.tex`])).toString(),'Before.\n');
    assert.equal((await git([...base,'show',`${b}:main.tex`])).toString(),'After.\n');
  }finally{await rm(dir,{recursive:true,force:true});}
});
