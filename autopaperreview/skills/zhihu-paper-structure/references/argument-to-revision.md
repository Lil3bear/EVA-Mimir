# Argument-to-Revision Playbook

Source inspiration: **丁霄汉**, [宏观布局](https://zhuanlan.zhihu.com/p/593195527). Procedures, tests and examples below are independently written extensions, not quotations or a reconstruction of inaccessible source text.

## Recover the Actual Work

Use the current active manuscript and available code/results. Before a full-paper restructuring, capture:

| Field | Required content | Evidence boundary |
| --- | --- | --- |
| Setting | Task, input, output, deployment assumptions | Simulator-state inputs cannot silently become RGB perception |
| Failure | Concrete failure of a relevant alternative | An illustration is not measured prevalence |
| Mechanism | Operation that addresses the failure | Name the transformed object and decision rule, not just a module |
| Ownership | Inherited / adapted / new / proposed | Upstream results do not become this fork's results |
| Evidence | Artifact, version, condition, comparison, result | Code proves implementation, not achieved performance |
| Boundary | Untested variants and negative observations | Preserve caveats that change the conclusion |

For local comments, fill only affected fields. Do not produce a ceremonial full-paper report for a sentence edit.

## Recover the Central Argument

Write a working statement: under [setting], [failure] motivates [mechanism], and [specific evidence] supports [bounded conclusion]. Keep unsupported slots unresolved. Connect each challenge to its design choice, operational change, discriminating comparison, and available evidence.

Useful challenge: the target moves after an action chunk is committed, making part of the command stale. Weak challenge: 'the dynamic module is difficult.' The mechanism must explain how the next observation changes the command, or identify that capability as proposed.

Prefer one central argument while preserving distinct contributions. Do not force a recorder into a learned world-model story. A research agenda can connect complementary projects without asserting an integrated system.

## Repair Section Roles

| Section | Reader must learn | Common mismatch | Smallest repair |
| --- | --- | --- | --- |
| Title / abstract | Task, distinctive idea, demonstrated outcome | Larger system than evidence supports | Name the tested setting and narrow the claim |
| Introduction | Failure, prior scope, necessary design choice | History or component inventory replaces problem | Keep background needed to explain the failure |
| Contributions | Authored object and supporting evidence | Renamed inherited parts appear new | Separate new method, resource and analysis with attribution |
| Method opening | Complete final input-to-output operation | Only one submodule explained | Add a concise overview with consistent roles |
| Method details | Definitions needed to execute the operation | Debugging chronology drives the outline | Organize by dependencies, retain meaningful failures in analysis |
| Experiments | Which claim each comparison tests | Leaderboard used as mechanism evidence | Explain the contrast, keep missing controls open |
| Conclusion | Supported takeaway and boundaries | Broader than protocol and introduction | Align transfer, robustness and safety claims |

No fixed paragraph count or mandatory section template. Explain why each move helps this paper.

## Contribution Ownership

Identify the exact authored object behind each contribution sentence. 'We use X' is context, not automatically novelty. 'We extend X with Y' must explain what Y changes. A benchmark needs an actual construction/protocol artifact, not desired tasks. Systems integration can be a contribution when its technical difficulty and evaluation are explicit.

If authors built a framework and a small final refinement, do not attribute only the refinement to them. If a public backbone supplies a capability, do not erase its source. Retain both sides of the distinction.

## Apply and Verify

Record current location, argument mismatch, smallest move/rewrite, source basis, dependent sections, verification. After an authorized edit, reread abstract, contributions, method overview, relevant captions and conclusion together.

Closure: same task and component roles throughout; no prose-created mechanism; material claims match evidence level; prior-work exceptions remain; removed claims are scope repairs, not completed experiments.

For research slides, keep one mechanism or scientific question per page, with provenance in notes. Distinguish existing prototype, implemented path and proposal. A teaser image is not evidence of closed-loop task success.
