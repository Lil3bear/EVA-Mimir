import {test} from "node:test";
import assert from "node:assert/strict";
import {archiveAppliedComments,commentSnapshot} from "../server/comment-log.mjs";

test("only effective open comments move into an immutable revision log without being resolved or deleted",()=>{
  const project={comments:[{id:"changed",body:"My exact opinion",quote:"Original sentence",status:"open"},{id:"untouched",body:"Still pending",status:"open"},{id:"resolved",status:"resolved"}]};
  const proposal={id:"proposal",revision:"old",archiveComments:true,effectiveCommentIds:["changed","resolved"]};
  archiveAppliedComments(project,proposal,"new","2026-10-18T00:00:00Z");
  assert.equal(project.comments.length,3);assert.equal(project.comments[0].status,"open");
  assert.equal(project.comments[0].archiveProposalId,"proposal");assert.equal(project.comments[1].archivedAt,undefined);
  assert.equal(project.comments[2].archivedAt,undefined);assert.equal(proposal.commentLog.length,1);
  assert.equal(proposal.commentLog[0].body,"My exact opinion");assert.equal(proposal.commentLog[0].resultRevision,"new");
  project.comments[0].body="A later opinion";
  assert.equal(proposal.commentLog[0].body,"My exact opinion");
});
test("no-op or legacy proposals do not archive comments and snapshots detect in-flight user changes",()=>{
  const project={comments:[{id:"c1",body:"Before",quote:"Source",status:"open"}]};
  for(const proposal of [{id:"old",effectiveCommentIds:["c1"]},{id:"noop",archiveComments:true,effectiveCommentIds:[]}])archiveAppliedComments(project,proposal,"r2","now");
  assert.equal(project.comments[0].archivedAt,undefined);
  const saved=commentSnapshot(project.comments[0]);
  assert.deepEqual(commentSnapshot({...project.comments[0],page:9}),saved);
  assert.notDeepEqual(commentSnapshot({...project.comments[0],body:"Changed"}),saved);
  assert.notDeepEqual(commentSnapshot({...project.comments[0],status:"resolved"}),saved);
});
test("an effective language edit does not archive an explicitly retained scientific concern",()=>{
  const project={comments:[{id:"partial",status:"open",body:"Need actual experimental evidence"},{id:"complete",status:"open",body:"Fix this wording"}]};
  const proposal={id:"p",revision:"r",archiveComments:true,effectiveCommentIds:["partial","complete"],keepOpenCommentIds:["partial"]};
  archiveAppliedComments(project,proposal,"r2","now");
  assert.equal(project.comments[0].archivedAt,undefined);
  assert.equal(project.comments[1].archiveProposalId,"p");
  assert.deepEqual(proposal.commentLog.map(c=>c.id),["complete"]);
});
