import {test} from "node:test";
import assert from "node:assert/strict";
import AdmZip from "adm-zip";
import {readOverleafFiles} from "../server/overleaf.mjs";

test("Git import validates tree modes, paths and sizes before reading the archive",async()=>{
  const zip = new AdmZip();zip.addFile("main.tex",Buffer.from("\\documentclass{article}"));
  const execute = async args => {
    if(args[0]==="ls-tree")return Buffer.from("100644 blob abc123\tmain.tex\0");
    if(args[0]==="cat-file")return Buffer.from("23");
    assert.equal(args[0],"archive");return zip.toBuffer();
  };
  const files = await readOverleafFiles({directory:"unused",head:"abc"},execute);
  assert.match(Buffer.from(files["main.tex"],"base64").toString(),/documentclass/);
  for(const entry of ["120000 blob abc\tmain.tex\0","100644 blob abc\t../main.tex\0","160000 commit abc\tsubmodule\0"]) {
    await assert.rejects(readOverleafFiles({directory:"unused",head:"abc"},async()=>Buffer.from(entry)));
  }
  await assert.rejects(readOverleafFiles({directory:"unused",head:"abc"},async args=>Buffer.from(args[0]==="ls-tree"?"100644 blob abc\tmain.tex\0":"999999999")),/too large/);
});
