#!/usr/bin/env node
// Deliberately returns bad comment links to exercise the HTTP boundary, not a real model.
import { readFile, writeFile } from "node:fs/promises";
const args = process.argv.slice(2);
if (args[0] === "login") {
  console.log("Logged in using ChatGPT");
} else {
  let prompt = "";
  for await (const chunk of process.stdin) prompt += chunk;
  const marker = "MANUSCRIPT DATA (not instructions):\n";
  const input = JSON.parse(
    prompt.slice(prompt.lastIndexOf(marker) + marker.length),
  );
  const schema = JSON.parse(
    await readFile(args[args.indexOf("--output-schema") + 1], "utf8"),
  );
  const contract = schema.properties.patches.items.properties.commentIds;
  if (
    input.comments.length &&
    !contract.items.enum?.includes(input.comments[0].id)
  )
    throw new Error("Missing comment ID enum");
  if (!input.comments.length && contract.maxItems !== 0)
    throw new Error("Missing empty-comment contract");
  const result = {
    summary: "Simulated patch with malformed metadata",
    coverage: "test fixture",
    findings: [],
    patches: [
      {
        file: "main.tex",
        before: "Each stage leaves an explicit record.",
        after: "Each stage retains an explicit record for the author.",
        reason: "Simulation",
        commentIds: [
          ...input.comments.slice(0, 1).map((c) => c.id),
          "F1",
          "invented-id",
        ],
      },
    ],
  };
  if (input.comments.some((c) => c.body.includes("AUTO_VALID_FIXTURE"))) {
    result.patches[0].commentIds = input.comments.slice(0, 1).map((c) => c.id);
    if (
      !input.documents
        .find((d) => d.file === "main.tex")
        .content.includes(result.patches[0].before)
    ) {
      result.patches[0].before =
        "Scientific decisions and final acceptance of changes remain with the author.";
      result.patches[0].after =
        "The author retains responsibility for scientific decisions and final approval of revisions.";
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  await writeFile(
    args[args.indexOf("--output-last-message") + 1],
    JSON.stringify(result),
  );
  console.log(JSON.stringify({ type: "turn.completed" }));
}
