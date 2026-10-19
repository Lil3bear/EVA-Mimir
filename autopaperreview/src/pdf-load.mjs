export function retryablePDFError(error) {
  if(["AbortException","RenderingCancelledException","InvalidPDFException","MissingPDFException"].includes(error?.name))return false;
  if(error?.status)return [502,503,504,520,522,523,524].includes(Number(error.status));
  return /(?:\b(?:50[234]|52[0234])\b|failed to fetch|network|fetch failed|connection|load failed)/i.test(error?.message||"");
}

export function pdfErrorMessage(error) {
  if(Number(error?.status)===401)return "登录已过期，请重新登录后加载 PDF。";
  if(Number(error?.status)===403)return "当前账号无权读取此 PDF。";
  if(Number(error?.status)===404 || error?.name==="MissingPDFException")return "此版本 PDF 不存在，请先编译。";
  if(error?.name==="InvalidPDFException")return "PDF 文件不完整或格式无效，请重新编译。";
  return "PDF 暂时加载失败，请重新加载。论文与批注未改变。";
}

// Retry only this read, with the same immutable URL; destroying cancels pending retries.
export function loadPDF(getDocument,options,{onRetry=()=>{},delays=[750,1500]}={}) {
  let task,canceled=false,timer,wake;
  const destroyTask=()=>{try{return Promise.resolve(task?.destroy()).catch(()=>{});}catch{return Promise.resolve();}};
  const promise=(async()=>{
    for(let attempt=0;;attempt++) {
      if(canceled)throw Object.assign(Error("PDF loading cancelled"),{name:"AbortException"});
      try {
        task=getDocument({...options});
        const doc=await task.promise;
        if(canceled){await destroyTask();throw Object.assign(Error("PDF loading cancelled"),{name:"AbortException"});}
        return doc;
      } catch(error) {
        if(canceled || attempt>=delays.length || !retryablePDFError(error))throw error;
        await destroyTask();
        if(canceled)throw error;
        onRetry(attempt+1,delays.length);
        await new Promise(resolve=>{wake=resolve;timer=setTimeout(resolve,delays[attempt]);});
      }
    }
  })();
  return {promise,destroy(){canceled=true;clearTimeout(timer);wake?.();return destroyTask();}};
}
