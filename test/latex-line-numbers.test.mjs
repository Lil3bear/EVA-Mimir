import {test} from "node:test";
import assert from "node:assert/strict";
import {mkdtemp,rm} from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import {compileFiles} from "../server/core.mjs";

test("two-column review line numbers stay in the outer margins after bibliography stabilization",{timeout:30000},async()=>{
  const directory=await mkdtemp(path.join(os.tmpdir(),"mimir-lineno-"));
  const paragraph="A review document needs stable line references across both columns. The source remains unchanged while the bibliography and floating objects determine the final page layout. ";
  const source=String.raw`\documentclass[10pt,twocolumn,letterpaper]{article}
\usepackage[switch]{lineno}
\usepackage{natbib}
\renewcommand\linenumberfont{\normalfont\ttfamily\scriptsize}
\linenumbers
\begin{document}
\twocolumn[{\section*{Review layout regression}}]
This source cites a real fixture entry \citep{fixture}.
\begin{table*}[t]\centering\begin{tabular}{ll}Condition & Result\\Fixed source & Stable margins\end{tabular}\caption{A wide float changes column boundaries.}\end{table*}
`+Array.from({length:30},()=>paragraph.repeat(3)).join("\n\n")+String.raw`
\bibliographystyle{plainnat}
\bibliography{refs}
\end{document}`;
  const files={"main.tex":Buffer.from(source).toString("base64"),"refs.bib":Buffer.from("@article{fixture,author={Example, A.},title={Layout Fixture},journal={Test},year={2026}}").toString("base64")};
  let document;
  try {
    const progress=[];
    const result=await compileFiles(files,"main.tex","pdflatex",directory,{onProgress:event=>progress.push(event)});
    assert.equal(progress.length,4);
    assert.match(progress.at(-1).message,/4\/4/);
    const {getDocument}=await import("pdfjs-dist/legacy/build/pdf.mjs");
    document=await getDocument({data:new Uint8Array(result.pdf),isEvalSupported:false,useSystemFonts:true}).promise;
    let count=0;
    for(let number=1;number<=document.numPages;number++){
      const page=await document.getPage(number),text=await page.getTextContent();
      const lineNumbers=text.items.filter(item=>/^\d+$/.test(item.str)&&text.styles[item.fontName]?.fontFamily==="monospace");
      count+=lineNumbers.length;
      for(const item of lineNumbers)assert(item.transform[4]<100||item.transform[4]>500,`Page ${number}: line ${item.str} appeared inside the text columns`);
    }
    assert(count>100,"The fixture must actually exercise multi-column line numbering");
  } finally {await document?.destroy();await rm(directory,{recursive:true,force:true});}
});
