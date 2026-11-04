export function pdfFixture() {
  const sentences = [
    "Our method improves physical validity.",
    "The comparison also changes supervision.",
    "Appendix A describes the training data and evaluation protocol.",
    "The experiment supports a system-level result, not isolated causality.",
  ];
  const stream = `BT /F1 20 Tf 48 720 Td (Evidence-Grounded Paper Review) Tj\n/F1 10 Tf 0 -24 Td (Review workflow test fixture - not a research submission) Tj\n/F1 13 Tf 0 -42 Td (Abstract) Tj\n/F1 11 Tf ${sentences.map(line => `0 -20 Td (${line}) Tj`).join("\n")}\n/F1 13 Tf 0 -45 Td (1. Introduction) Tj\n/F1 11 Tf 0 -22 Td (This document is a deterministic PDF fixture for browser tests.) Tj\n0 -20 Td (It contains selectable text, page geometry and source evidence.) Tj\n0 -20 Td (No AI review is generated or represented as a human assessment.) Tj\n/F1 13 Tf 0 -45 Td (2. Evidence and evaluation) Tj\n/F1 11 Tf 0 -22 Td (A claim should be evaluated against its stated assumptions.) Tj\n0 -20 Td (An observation is not a causal explanation of an improvement.) Tj\n0 -20 Td (The reviewer should consider the strongest counterevidence.) Tj\n/F1 13 Tf 0 -45 Td (Appendix A. Protocol) Tj\n/F1 11 Tf 0 -22 Td (All test records are isolated from the real review library.) Tj\n0 -20 Td (Quoted evidence must match the specified physical PDF page.) Tj\n0 -20 Td (Prior drafts and model interactions remain independently stored.) Tj ET`;
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`];
  let content = "%PDF-1.4\n", offsets = [0];
  objects.forEach((object, i) => { offsets.push(Buffer.byteLength(content)); content += `${i + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = Buffer.byteLength(content);
  content += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.slice(1).map(n => `${String(n).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(content);
}
