import {createHash} from "node:crypto";
import {z} from "zod";

export const figureModels=["gpt-6.1-sol","gpt-6-astra"];
export const patterns=["comparison","layers","pipeline-inset","architecture","decision-tree","worked-example"];
const label=z.string().min(1).max(70).regex(/^[\x20-\x7e]+$/, "图内使用简短英文标注");
const caption=z.string().min(1).max(600).regex(/^[\x20-\x7e]+$/, "图注使用英文");
const id=z.string().regex(/^[a-zA-Z][a-zA-Z0-9_-]{0,30}$/);
export const diagramSchema=z.object({title:label,caption,takeaway:z.string().min(1).max(1500),pattern:z.enum(patterns),nodes:z.array(z.object({id,label,column:z.number().int().min(0).max(3),row:z.number().int().min(0).max(3),role:z.enum(["context","motivation","novelty","evaluation"])}).strict()).min(2).max(12),edges:z.array(z.object({from:id,to:id,label:label.max(28)}).strict()).max(18),evidence:z.array(z.object({file:z.string(),quote:z.string().min(1),supports:z.string().min(1)}).strict()).min(1),blockers:z.array(z.string())}).strict();
const string={type:"string"};
const obj=properties=>({type:"object",additionalProperties:false,required:Object.keys(properties),properties});
const array=items=>({type:"array",items});
export const diagramWireSchema=obj({title:string,caption:string,takeaway:string,pattern:{type:"string",enum:patterns},nodes:array(obj({id:string,label:string,column:{type:"integer"},row:{type:"integer"},role:{type:"string",enum:["context","motivation","novelty","evaluation"]}})),edges:array(obj({from:string,to:string,label:string})),evidence:array(obj({file:string,quote:string,supports:string})),blockers:array(string)});
export const auditWireSchema=obj({summary:string,blockers:array(obj({file:string,quote:string,reason:string}))});
export const chartWireSchema=obj({tableId:string,title:string,caption:string,takeaway:string,rows:array({type:"integer"}),columns:array({type:"integer"}),unit:{type:"string",enum:["percent","count"]},blockers:array(string)});

export const sha=value=>createHash("sha256").update(Buffer.isBuffer(value)||typeof value==="string"?value:JSON.stringify(value)).digest("hex");
export function manuscript(revision) {
  return Object.entries(revision.files).filter(([f])=>/\.(tex|bib|md|csv)$/i.test(f)).map(([file,data])=>({file,content:Buffer.from(data,"base64").toString("utf8")}));
}

// Strip comments without mistaking escaped percent signs for comment delimiters.
function uncomment(text) {return text.split("\n").map(line=>{for(let i=0;i<line.length;i++)if(line[i]==="%" && (line.slice(0,i).match(/\\+$/)?.[0].length||0)%2===0)return line.slice(0,i);return line;}).join("\n");}
function plain(cell) {
  return cell.replace(/\\(?:toprule|midrule|bottomrule|hline|quad|small|centering)\b/g," ").replace(/\\(?:rowcolor|cellcolor)\{[^{}]*\}/g,"").replace(/\\textcolor\{[^{}]*\}/g,"").replace(/\\(?:textbf|textit|textrm|boldsymbol)\b/g,"").replace(/\$\^?\\dagger\$/g,"").replace(/\\&/g,"&").replace(/\\%/g,"%").replace(/[{}$]/g,"").replace(/\\[a-zA-Z]+/g,"").replace(/\s+/g," ").trim();
}
export function figureInventory(revision,main) {
  const documents=manuscript(revision),byFile=new Map(documents.map(d=>[d.file,uncomment(d.content)])),active=new Set();
  const visit=file=>{if(active.has(file)||!byFile.has(file))return;active.add(file);for(const match of byFile.get(file).matchAll(/\\(?:input|include)\s*\{([^{}]+)\}/g)){const f=match[1].endsWith(".tex")?match[1]:`${match[1]}.tex`;visit(byFile.has(f)?f:`${file.slice(0,file.lastIndexOf("/")+1)}${f}`);}};
  visit(main);
  const assets=Object.keys(revision.files).filter(f=>/\.(pdf|png|jpe?g|eps|svg)$/i.test(f)).map(file=>({file,sha256:sha(Buffer.from(revision.files[file],"base64")),references:[]}));
  const tables=[];
  for(const [file,text] of byFile){
    if(!/\.tex$/i.test(file))continue;
    for(const m of text.matchAll(/\\includegraphics(?:\[[^\]]*\])?\s*\{([^{}]+)\}/g)) {
      const asset=assets.find(a=>a.file===m[1]||a.file.replace(/\.[^.]+$/,"")===m[1]);
      if(asset)asset.references.push({file,active:active.has(file)});
    }
    for(const m of text.matchAll(/\\begin\{table\*?\}([\s\S]*?)\\end\{table\*?\}/g)){
      const labelId=m[1].match(/\\label\{([^{}]+)\}/)?.[1];
      const tabular=m[1].match(/\\begin\{tabular\*?\}([\s\S]*?)\\end\{tabular\*?\}/)?.[1];
      if(!labelId||!tabular)continue;
      // A deliberately bounded subset: only complete numeric rows from ordinary tabular cells.
      // Multi-column group rows stay as context, never guessed into data cells.
      const rows=[];let group="";
      for(const raw of tabular.split(/\\\\(?:\[[^\]]*\])?/).slice(1)){
        if(/\\multicolumn/.test(raw)){group=plain(raw);continue;}
        const cells=raw.split(/(?<!\\)&/).map(plain);
        if(cells.length<2||!cells.slice(1).every(c=>/^[+\-]?\d+(?:\.\d+)?$/.test(c)))continue;
        rows.push({label:cells[0],cells,group,values:cells.slice(1).map(Number)});
      }
      // Header is kept verbatim so semantic choices remain inspectable and evidence-bound.
      const header=tabular.split(/\\\\/)[0];
      const headers=(header.split(/\\toprule/).at(-1)).split(/(?<!\\)&/).map(plain);
      if(rows.length)tables.push({id:labelId,file,active:active.has(file),raw:m[0],rows,header,headers});
    }
  }
  return {assets,tables,activeFiles:[...active]};
}

export function validateDiagram(raw,documents) {
  const d=diagramSchema.parse(raw),ids=new Set(),slots=new Set();
  for(const n of d.nodes){const slot=`${n.column}:${n.row}`;if(ids.has(n.id)||slots.has(slot))throw Error("图形节点编号或位置重复");ids.add(n.id);slots.add(slot);}
  if(d.edges.some(e=>!ids.has(e.from)||!ids.has(e.to)||e.from===e.to))throw Error("图形连线引用无效节点");
  for(const e of d.evidence)if(!documents.find(doc=>doc.file===e.file)?.content.includes(e.quote))throw Error("图形论断无法定位到当前原文");
  return d;
}
export function resolveChart(raw,tables) {
  const d=z.object({tableId:z.string(),title:label,caption,takeaway:z.string(),rows:z.array(z.number().int().nonnegative()).min(1).max(12),columns:z.array(z.number().int().min(1)).min(1).max(3),unit:z.enum(["percent","count"]),blockers:z.array(z.string())}).strict().parse(raw);
  const table=tables.find(t=>t.id===d.tableId&&t.active);
  if(!table)throw Error("实验图表必须使用当前正文的已解析表格");
  if(new Set(d.rows).size!==d.rows.length||new Set(d.columns).size!==d.columns.length)throw Error("图表行列重复");
  const series=d.columns.map(c=>table.headers[c]);
  if(series.some(s=>!s||/Delta|delta|Δ/.test(s)))throw Error("无法确认数值列含义；差值与绝对值请分开制图");
  if(series.some(s=>d.unit==="percent"?/number|count|solved|tasks/i.test(s):/%|rate|base|harness|day/i.test(s)))throw Error("图表单位与表格列含义不一致");
  const rows=d.rows.map(r=>{const row=table.rows[r];if(!row)throw Error("图表行不存在");return {label:row.label,group:row.group,values:d.columns.map(c=>{if(row.cells[c]===undefined)throw Error("图表列不存在");const v=Number(row.cells[c]);if(!Number.isFinite(v)||v<0||(d.unit==="percent"&&v>100))throw Error("图表数值或单位范围无效");return v;})};});
  if(new Set(rows.map(r=>r.group)).size>1)throw Error("不同配置的表格分组不能放进同一受控比较图，请分别制图");
  return {...d,series,source:{file:table.file,tableId:table.id,tableHash:sha(table.raw),header:table.header,rows:d.rows,columns:d.columns},data:rows};
}

const colors={context:"#e8edf0",motivation:"#f7d8d5",novelty:"#ccebe3",evaluation:"#f3e4b8"};
function wrap(text,limit=24){const lines=[];let line="";for(const word of text.split(/\s+/)){if(word.length>limit)throw Error("图内标注单词过长，请缩短");if(`${line} ${word}`.trim().length>limit){lines.push(line);line=word;}else line=`${line} ${word}`.trim();}if(line)lines.push(line);if(lines.length>3)throw Error("图内标注过长，请缩短");return lines;}
export function sceneFor(d,kind="diagram") {
  const columns=kind==="diagram"?Math.max(...d.nodes.map(n=>n.column))+1:4;
  const rowCount=kind==="diagram"?Math.max(...d.nodes.map(n=>n.row))+1:1;
  const width=columns<=2?600:1200,diagramHeight=Math.max(320,rowCount*155+130),height=kind==="chart"?Math.max(480,d.data.length*76+190):diagramHeight+Math.ceil(d.edges.length/2)*42,shapes=[];
  const text=(x,y,value,size=22,anchor="start")=>shapes.push({type:"text",x,y,text:value,size,anchor,fill:"#172b32"});
  shapes.push({type:"rect",x:0,y:0,w:width,h:height,fill:"#ffffff",stroke:"none"});wrap(d.title,width===600?40:70).forEach((line,i)=>text(30,36+i*25,line,24));
  if(kind==="chart"){
    const max=d.unit==="percent"?100:Math.max(1,...d.data.flatMap(r=>r.values))*1.1,left=330,plot=790,top=120;
    for(let t=0;t<=4;t++){const v=max*t/4,x=left+plot*t/4;shapes.push({type:"line",x1:x,y1:top-15,x2:x,y2:height-65,stroke:"#d9e0e2"});text(x,height-32,String(Number(v.toFixed(1))),18,"middle");}
    d.data.forEach((r,i)=>{const y=top+i*76;wrap(r.label,25).forEach((s,j)=>text(20,y+16+j*20,s,19));r.values.forEach((v,j)=>{const bh=48/r.values.length,barY=y+j*bh;shapes.push({type:"rect",x:left,y:barY,w:plot*v/max,h:bh-4,fill:["#5b9fa2","#d4a648","#b97487"][j],stroke:"none"});text(Math.min(1160,left+plot*v/max+6),barY+bh-8,String(v),18);});});
    text(40,80,`${d.unit==="percent"?"Rate (%)":"Count"} | no uncertainty estimates`,18);
    d.series.forEach((name,j)=>{const x=390+j*260;shapes.push({type:"rect",x,y:61,w:14,h:14,fill:["#5b9fa2","#d4a648","#b97487"][j],stroke:"none"});text(x+20,75,name,17);});
  }else{
    const cols=columns,rows=rowCount,cw=(width-60)/cols,rh=(diagramHeight-140)/rows,bw=Math.min(cw-30,330),bh=Math.min(rh-32,112);
    const pos=new Map(d.nodes.map(n=>[n.id,{x:30+n.column*cw+(cw-bw)/2,y:90+n.row*rh,w:bw,h:bh}]));
    for(const [index,e] of d.edges.entries()){const a=pos.get(e.from),b=pos.get(e.to);let points;
      if(a.x===b.x)points=[[a.x+a.w/2,a.y+(b.y>a.y?a.h:0)],[b.x+b.w/2,b.y+(b.y>a.y?0:b.h)]];
      else {const forward=b.x>a.x,x1=a.x+(forward?a.w:0),x2=b.x+(forward?0:b.w),mid=(x1+x2)/2;points=[[x1,a.y+a.h/2],[mid,a.y+a.h/2],[mid,b.y+b.h/2],[x2,b.y+b.h/2]];}
      for(const [node,p] of pos)if(node!==e.from&&node!==e.to)for(let k=1;k<points.length;k++){
        const [x1,y1]=points[k-1],[x2,y2]=points[k];
        const crosses=x1===x2?x1>p.x&&x1<p.x+p.w&&Math.max(y1,y2)>p.y&&Math.min(y1,y2)<p.y+p.h:y1>p.y&&y1<p.y+p.h&&Math.max(x1,x2)>p.x&&Math.min(x1,x2)<p.x+p.w;
        if(crosses)throw Error("图形连线穿过其他模块，请调整节点布局后重新生成");
      }
      shapes.push({type:"path",points,stroke:"#64757e",arrow:true});const p=points.length===2?[(points[0][0]+points[1][0])/2,(points[0][1]+points[1][1])/2]:points[1];
      shapes.push({type:"rect",x:p[0]-9,y:p[1]-13,w:18,h:23,fill:"#ffffff",stroke:"none"});text(p[0],p[1]+5,String(index+1),18,"middle");
      wrap(`${index+1}. ${e.label}`,width===600?26:52).forEach((s,j)=>text(30+(index%2)*(width/2),diagramHeight-20+Math.floor(index/2)*42+j*18,s,18));
    }
    for(const n of d.nodes){const p=pos.get(n.id);shapes.push({type:"rect",...p,fill:colors[n.role],stroke:n.role==="novelty"?"#39796f":"#819198"});const lines=wrap(n.label,Math.floor(bw/12));lines.forEach((s,i)=>text(p.x+p.w/2,p.y+p.h/2+(i-(lines.length-1)/2)*25+7,s,22,"middle"));}
    text(30,height-20,"Coral: motivation | Green: novelty",16);
  }
  return {width,height,shapes};
}
const escape=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&apos;"}[c]));
export function sceneSVG(scene) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${scene.width}" height="${scene.height}" viewBox="0 0 ${scene.width} ${scene.height}"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0 0 L7 3 L0 6" fill="none" stroke="#64757e"/></marker></defs>${scene.shapes.map(s=>s.type==="text"?`<text x="${s.x}" y="${s.y}" font-family="Helvetica,Arial,sans-serif" font-size="${s.size}" text-anchor="${s.anchor}" fill="${s.fill}">${escape(s.text)}</text>`:s.type==="rect"?`<rect x="${s.x}" y="${s.y}" width="${s.w}" height="${s.h}" rx="4" fill="${s.fill}" stroke="${s.stroke}"/>`:s.type==="line"?`<line x1="${s.x1}" y1="${s.y1}" x2="${s.x2}" y2="${s.y2}" stroke="${s.stroke}"/>`:`<polyline points="${s.points.map(p=>p.join(",")).join(" ")}" fill="none" stroke="${s.stroke}" stroke-width="2" marker-end="url(#arrow)"/>`).join("")}</svg>`;
}
