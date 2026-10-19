// Isolated copy only. The local model stub never contacts a paid provider.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import assert from 'node:assert/strict';
import {spawn,execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {createServer} from 'node:http';
import {randomUUID,createHash} from 'node:crypto';
import {atomicJSON} from '../server/core.mjs';
const root=path.resolve(import.meta.dirname,'..');
if(!process.env.LOAD_PROJECT_DIR)throw Error('Set LOAD_PROJECT_DIR to an existing trusted local project directory; the test modifies only an isolated copy.');
const sourceDir=path.resolve(process.env.LOAD_PROJECT_DIR);
const data=await fs.mkdtemp(path.join(os.tmpdir(),'autopaper-team-load-'));
const original=await fs.readFile(path.join(sourceDir,'project.json'));
const hash=x=>createHash('sha256').update(x).digest('hex');
const source=JSON.parse(original), revision=JSON.parse(await fs.readFile(path.join(sourceDir,'revisions',source.revision+'.json')));
const id=randomUUID(),rid=randomUUID(),directory=path.join(data,id),file=process.env.LOAD_TEX_FILE||'main.tex';
assert(revision.files[file]);
revision.files[file]=Buffer.from(Buffer.from(revision.files[file],'base64').toString()+'\n'+Array.from({length:10},(_,i)=>`% LOADTEST_SLOT_${i}`).join('\n')+'\n').toString('base64');
Object.assign(revision,{id:rid,parent:null,gitCommit:undefined});
const project={...source,id,revision:rid,pdfRevision:rid,comments:[],automation:{enabled:false},overleaf:undefined,sourceGit:null,history:[{id:rid,time:revision.time,label:'Isolated load fixture'}]};
await atomicJSON(path.join(directory,'project.json'),project);
await atomicJSON(path.join(directory,'revisions',rid+'.json'),revision);
await fs.copyFile(path.join(sourceDir,source.pdfRevision+'.pdf'),path.join(directory,rid+'.pdf'));
const metrics={},calls=[];
let child;
const model=createServer(async(req,res)=>{
 try {
  let body='';for await(const chunk of req)body+=chunk;
  const payload=JSON.parse(body),input=JSON.parse(payload.messages.at(-1).content);
  calls.push(payload.model);
  await new Promise(r=>setTimeout(r,600));
  const patches=input.comments.filter(c=>c.body.startsWith('LOADTEST ')).map(c=>{
    const n=Number(c.body.split(' ')[1]);
    return {file,before:`% LOADTEST_SLOT_${n}`,after:`% LOADTEST_DONE_${n}`,reason:'Isolated concurrency fixture, not scientific editing',commentIds:[c.id]};
  });
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify({model:'loadtest-fixture',choices:[{finish_reason:'stop',message:{content:JSON.stringify({summary:'Load fixture',coverage:'Synthetic TeX comments only',findings:[],patches})}}]}));
 }catch(e){res.statusCode=500;res.end(JSON.stringify({error:e.message}));}
});
await new Promise(r=>model.listen(0,'127.0.0.1',r));
const port=Number(process.env.LOAD_TEST_PORT||4497),base=`http://127.0.0.1:${port}/api/projects/${id}`;
async function request(url=base,options={}){
 const start=performance.now();
 const r=await fetch(url,{...options,signal:AbortSignal.timeout(120000),headers:{'Content-Type':'application/json',...options.headers},body:options.body?JSON.stringify(options.body):undefined});
 const bytes=Buffer.from(await r.arrayBuffer());
 return {status:r.status,ms:Math.round(performance.now()-start),bytes:bytes.length,data:r.headers.get('content-type')?.includes('json')?JSON.parse(bytes):bytes,encoding:r.headers.get('content-encoding')};
}
function measure(name,rows){const times=rows.map(r=>r.ms).sort((a,b)=>a-b);metrics[name]={requests:rows.length,statuses:rows.reduce((o,r)=>(o[r.status]=(o[r.status]||0)+1,o),{}),p50ms:times[Math.floor(times.length*.5)],p95ms:times[Math.min(times.length-1,Math.floor(times.length*.95))],maxMs:times.at(-1)};}
try{
 child=spawn(process.execPath,['server/index.mjs'],{cwd:root,env:{...process.env,PORT:String(port),BIND_HOST:'127.0.0.1',DATA_DIR:data,NODE_ENV:'production',AI_PROVIDER:'openai',OPENAI_API_KEY:'local-fixture-not-a-key',OPENAI_BASE_URL:`http://127.0.0.1:${model.address().port}/v1`,OPENAI_MODEL:'loadtest-fixture',AI_API_FORMAT:'chat-json',LOCAL_REVISION_ONLY:'0',REVISION_REVIEWER:'',REVISION_COWRITER_MODEL:'',REVISION_TEAM_MODE:'',SHARED_MODE:'0',ARCHIVE_APPLIED_COMMENTS:'1'},stdio:['ignore','pipe','pipe']});
 let errors='';child.stderr.on('data',x=>errors+=x);
 await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(Error('Startup timed out '+errors)),15000);child.stdout.on('data',x=>{if(x.toString().includes('Autopaperreview:')){clearTimeout(timeout);resolve();}});child.once('exit',code=>{clearTimeout(timeout);reject(Error(`exit ${code}: ${errors}`));});});
 const readers=await Promise.all(Array.from({length:10},()=>request()));measure('10_project_readers',readers);assert(readers.every(r=>r.status===200&&r.encoding==='gzip'));
 const pdfs=await Promise.all(Array.from({length:10},()=>request(base+`/pdf/${rid}`)));measure('10_pdf_readers',pdfs);assert(pdfs.every(r=>r.status===200&&r.data.subarray(0,5).toString()==='%PDF-'));
 const poll=await Promise.all(Array.from({length:100},()=>request(base+'/activity')));measure('100_activity_reads',poll);assert(poll.every(r=>r.status===200&&r.data.projectVersion));
 const version=poll[0].data.projectVersion;
 const comments=await Promise.all(Array.from({length:10},(_,i)=>request(base+'/comments',{method:'POST',body:{body:`LOADTEST ${i}`,quote:`% LOADTEST_SLOT_${i}`,file,pdfRevision:rid}})));measure('10_comment_writers',comments);assert(comments.every(r=>r.status===200));
 let p=(await request()).data;assert.equal(p.comments.length,10);assert.equal(new Set(p.comments.map(c=>c.id)).size,10);assert.notEqual((await request(base+'/activity')).data.projectVersion,version);
 const input={mode:'revise',skillIds:['writing'],instructions:'Change only LOADTEST fixture markers.',consent:true,apply:true,commentIds:p.comments.map(c=>c.id)};
 const jobs=await Promise.all(Array.from({length:10},()=>request(base+'/jobs',{method:'POST',body:input})));measure('10_revision_submissions',jobs);assert.equal(jobs.filter(r=>r.status===202).length,1);assert.equal(jobs.filter(r=>r.status===409).length,9);
 let job;
 for(let i=0;i<240;i++){job=(await request(base+'/activity')).data.job;if(!['queued','running','cancelling'].includes(job.status))break;await new Promise(r=>setTimeout(r,500));}
 assert.equal(job.status,'completed',JSON.stringify(job));assert.equal(calls.length,1);
 p=(await request()).data;assert.equal(p.pdfRevision,p.revision);assert(p.comments.every(c=>c.addressed&&c.archivedAt));assert.equal(p.history[0].provenance.model,'loadtest-fixture');
 let current=(await request(base+`/source?file=${file}`)).data;
 for(let i=0;i<10;i++)assert(current.content.includes(`% LOADTEST_DONE_${i}`));
 const edits=await Promise.all(Array.from({length:10},(_,i)=>request(base+'/source',{method:'PUT',body:{file,revision:current.revision,content:current.content+`\n% CONCURRENT_AUTHOR_${i}\n`}})));measure('10_conflicting_source_writes',edits);assert.equal(edits.filter(r=>r.status===200).length,1);assert.equal(edits.filter(r=>r.status===409).length,9);
 for(let i=0;i<10;i++)if(edits[i].status===409){const fresh=(await request(base+`/source?file=${file}`)).data;assert.equal((await request(base+'/source',{method:'PUT',body:{file,revision:fresh.revision,content:fresh.content+`\n% CONCURRENT_AUTHOR_${i}\n`}})).status,200);}
 p=(await request()).data;const editedRevision=p.revision;
 current=(await request(base+`/source?file=${file}`)).data;for(let i=0;i<10;i++)assert(current.content.includes(`% CONCURRENT_AUTHOR_${i}`));
 assert.equal(p.history.length,12);assert(p.history.every(r=>/^[a-f0-9]{40}$/.test(r.gitCommit)));
 const restored=await request(base+`/restore/${rid}`,{method:'POST'});assert.equal(restored.status,200);p=restored.data;assert.equal(p.pdfRevision,p.revision);assert.equal(p.history[0].restoredFrom,rid);assert.equal(p.history[0].parent,editedRevision);assert.equal(p.comments.length,10);assert(p.comments.every(c=>!c.addressed));
 assert.equal((await request(base+`/source?file=${file}`)).data.content,Buffer.from(revision.files[file],'base64').toString());
 assert.equal((await request(base+`/history/${editedRevision}/diff`)).status,200);
 const git=await promisify(execFile)('git',['--git-dir',path.join(directory,'source-history.git'),'fsck','--full']);
 assert.equal(hash(await fs.readFile(path.join(sourceDir,'project.json'))),hash(original),'Production changed during test');
 metrics.validation={compiledAIRevision:true,model:'loadtest-fixture',paidModelCalls:0,tenCommentsApplied:true,tenSourceEditsRetained:true,conflictsRejected:true,historyVersions:p.history.length,restoredSourceAndPDF:true,gitFsckPassed:true,productionUnchanged:true};
 await fs.mkdir(path.join(root,'artifacts/team-load'),{recursive:true});await atomicJSON(path.join(root,'artifacts/team-load/result.json'),metrics);
 console.log(JSON.stringify(metrics,null,2));
}finally{
 if(child&&child.exitCode===null){child.kill('SIGTERM');await new Promise(r=>child.once('close',r));}
 await new Promise(r=>model.close(r));await fs.rm(data,{recursive:true,force:true});
}
