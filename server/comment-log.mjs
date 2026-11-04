export function commentSnapshot(comment) {
  return Object.fromEntries(["id","body","quote","file","status","pdfRevision","archivedAt","addressed"].map(key=>[key,comment[key]??null]));
}

export function archiveAppliedComments(project,proposal,revision,time) {
  if(!proposal.archiveComments)return;
  const keepOpen=new Set(proposal.keepOpenCommentIds||[]);
  const changed=new Set((proposal.effectiveCommentIds||[]).filter(id=>!keepOpen.has(id)));
  const comments=project.comments.filter(c=>changed.has(c.id)&&c.status==="open"&&!c.archivedAt);
  proposal.commentLog=comments.map(c=>({...structuredClone(c),archivedAt:time,sourceRevision:proposal.revision,resultRevision:revision,pendingVerification:true}));
  for(const comment of comments)Object.assign(comment,{archivedAt:time,archiveProposalId:proposal.id});
}
