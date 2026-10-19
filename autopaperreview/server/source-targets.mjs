export function sourceTargets(files, comments) {
  const documents=Object.entries(files).filter(([file])=>/\.tex$/i.test(file)).map(([file,data])=>({file,source:Buffer.from(data,"base64").toString("utf8")}));
  const exact=[];
  for(const comment of comments||[]) {
    if(!comment.quote?.trim())break;
    const matches=[];
    for(const document of documents) {
      if(comment.file && comment.file!==document.file)continue;
      let start=document.source.indexOf(comment.quote);
      while(start>=0 && matches.length<2){
        matches.push({...document,start,end:start+comment.quote.length});
        start=document.source.indexOf(comment.quote,start+1);
      }
    }
    if(matches.length!==1)break;
    exact.push(matches[0]);
  }
  if(comments?.length && exact.length===comments.length) {
    const merged=[];
    for(const range of exact.sort((a,b)=>a.file.localeCompare(b.file)||a.start-b.start)) {
      const previous=merged.at(-1);
      if(previous?.file===range.file && range.start<=previous.end)previous.end=Math.max(previous.end,range.end);
      else merged.push({...range});
    }
    return merged.map((range,i)=>({id:`T${i+1}`,file:range.file,start:range.start,end:range.end,text:range.source.slice(range.start,range.end)}));
  }
  const targets=[];
  for(const {file,source} of documents) {
    let offset=0;
    for(const text of source.split(/(\r?\n[ \t]*\r?\n)/)) {
      if(text.trim())targets.push({id:`T${targets.length+1}`,file,start:offset,end:offset+text.length,text});
      offset+=text.length;
    }
  }
  return targets;
}

export function materializeTargets(files,targets,patches) {
  const byId=new Map(targets.map(t=>[t.id,t])),groups=new Map(),seen=new Set();
  for(const patch of patches) {
    const target=byId.get(patch.targetId);
    if(!target || seen.has(patch.targetId))throw Error("TeX 修改目标编号不存在或重复；请合并同一段落的修改");
    seen.add(patch.targetId);
    if(patch.after===target.text)continue;
    if(!groups.has(target.file))groups.set(target.file,[]);
    groups.get(target.file).push({...patch,target});
  }
  return [...groups].map(([file,edits])=>{
    const before=Buffer.from(files[file],"base64").toString("utf8");
    let after=before;
    // Offsets refer only to this immutable source snapshot; apply from the end, never fuzzy-match PDF prose.
    for(const edit of edits.sort((a,b)=>b.target.start-a.target.start)) {
      const t=edit.target;
      if(before.slice(t.start,t.end)!==t.text)throw Error("TeX 修改目标与源码版本不符");
      after=after.slice(0,t.start)+edit.after+after.slice(t.end);
    }
    return {file,before,after,reason:edits.map(e=>e.reason).join("\n"),commentIds:[...new Set(edits.flatMap(e=>e.commentIds))]};
  });
}
