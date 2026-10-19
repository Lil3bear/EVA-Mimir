import {chromium} from '@playwright/test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
const data=await fs.mkdtemp(path.join(os.tmpdir(),'autopaper-guide-'));
const origin='http://127.0.0.1:4496',out='public/guide/images';
await fs.mkdir(out,{recursive:true});
const child=spawn(process.execPath,['server/index.mjs'],{env:{...process.env,PORT:'4496',DATA_DIR:data,NODE_ENV:'production',AI_PROVIDER:'openai',OPENAI_API_KEY:'',OPENAI_MODEL:'demo-no-model-call',REVISION_REVIEWER:'',REVISION_TEAM_MODE:'',REVISION_COWRITER_MODEL:'',SHARED_MODE:'0'},stdio:['ignore','pipe','pipe']});
let browser;
try{
 await new Promise((resolve,reject)=>{child.stdout.on('data',x=>{if(x.toString().includes('Autopaperreview:'))resolve();});child.once('error',reject);child.once('exit',x=>reject(Error('server exit '+x)));});
 const form=new FormData();form.append('demo','true');form.append('trusted','true');
 let response=await fetch(origin+'/api/projects/import',{method:'POST',body:form});assert.equal(response.status,200);let p=await response.json();
 const base=origin+'/api/projects/'+p.id;
 async function api(url,body,method='POST'){const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const j=await r.json();assert.equal(r.status,200,JSON.stringify(j));return j;}
 p=await api(base+'/compile');
 await api(base+'/comments',{body:'请简化这句话，保留作者对科学结论的最终决定权，不新增实验结果。',quote:'Scientific decisions and final acceptance of changes remain with the author.',pdfRevision:p.revision,page:1,file:'main.tex'});
 const source=await (await fetch(base+'/source?file=main.tex')).json();
 await api(base+'/source',{file:'main.tex',revision:source.revision,content:source.content.replace('Scientific decisions and final acceptance of changes remain with the author.','Authors make scientific decisions and approve the final changes.')},'PUT');
 await api(base+'/compile');
 browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
 await page.addInitScript(id=>localStorage.setItem('autopaperreview-project',id),p.id);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin);await page.waitForFunction(()=>document.querySelectorAll('.textLayer span').length>20,{},{timeout:45000});
 await page.screenshot({path:out+'/01-workspace.png'});
 await page.evaluate(()=>{const span=Array.from(document.querySelectorAll('.textLayer span')).find(s=>s.textContent.includes('Scientific manuscripts'));if(!span)throw Error('Expected abstract text not rendered');const range=document.createRange();range.selectNodeContents(span);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);const r=range.getBoundingClientRect();span.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:r.left+10,clientY:r.bottom,button:2}));});
 await page.getByRole('textbox',{name:'批注意见'}).fill('请简化这句话，保留原意、数字和引用，不增加没有证据的结论。');
 await page.screenshot({path:out+'/02-comment.png'});
 await page.getByRole('button',{name:'关闭浮窗',exact:true}).click();
 async function shot(button,file){await page.getByRole('button',{name:button,exact:true}).click();await page.getByRole('dialog').waitFor();await page.screenshot({path:out+'/'+file});await page.getByRole('button',{name:'关闭',exact:true}).click();}
 await shot('审稿 Skills','03-skills.png');
 await shot('版本历史','04-history.png');
 await shot('导出项目','05-export.png');
 await shot('Overleaf 同步','06-overleaf.png');
 assert.equal(errors.length,0,errors.join('\n'));
 console.log(JSON.stringify({screenshots:6,demoOnly:true,modelCalls:0,productionUntouched:true}));
}finally{if(browser)await browser.close();child.kill('SIGTERM');await new Promise(r=>child.once('close',r));await fs.rm(data,{recursive:true,force:true});}
