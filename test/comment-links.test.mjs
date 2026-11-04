import { test } from "node:test";
import assert from "node:assert/strict";
import { linkPatchComments, applyPatches } from "../server/core.mjs";

test("unknown finding labels do not discard a valid patch or get guessed onto another comment", () => {
  const original = [
    {
      file: "main.tex",
      before: "Original sentence.",
      after: "Revised sentence.",
      reason: "test",
      commentIds: ["F1", "existing-id", "existing-id", "invented-id"],
    },
  ];
  const linked = linkPatchComments(original, [
    { id: "existing-id" },
    { id: "other-id" },
  ]);
  assert.deepEqual(linked[0].commentIds, ["existing-id"]);
  assert.deepEqual(linked[0].unlinkedCommentIds, ["F1", "invented-id"]);
  assert.equal(original[0].commentIds.length, 4);
  const updated = applyPatches(
    { "main.tex": Buffer.from("Original sentence.").toString("base64") },
    linked,
  );
  assert.equal(
    Buffer.from(updated["main.tex"], "base64").toString(),
    "Revised sentence.",
  );
});

test("instruction-only edits have no comment association and invalid source edits still fail", () => {
  const patches = linkPatchComments(
    [
      {
        file: "main.tex",
        before: "missing",
        after: "changed",
        commentIds: ["F1"],
      },
    ],
    [],
  );
  assert.deepEqual(patches[0].commentIds, []);
  assert.deepEqual(patches[0].unlinkedCommentIds, ["F1"]);
  assert.throws(
    () =>
      applyPatches(
        { "main.tex": Buffer.from("Original.").toString("base64") },
        patches,
      ),
    /失效/,
  );
});
