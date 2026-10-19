# Eight Application Modules: Ownership and Handoffs

These are the actual Autopaperreview IDs, not eight new agents or eight compulsory model calls. This map and the worksheets are independent engineering extensions. Original inspirations remain attributed in each module; Ding Xiaohan's articles supply writing and response principles, not these implementation contracts.

| App ID / name | Owns | Detailed worksheet | Closure evidence |
| --- | --- | --- | --- |
| writing / 学术表达 | Drafting and smallest authorized text repair | [Writing](writing.md) | Exact changed passage still expresses the supported meaning |
| review / 十维审稿 | Whole-paper diagnosis and adjudication of objections | [Review](review.md) | Objection checked against the strongest existing defense |
| claims / 论断与证据 | Claim strength, experimental attribution and evidence gaps | [Claims](claims.md) | Evidence answers the same claim under the same conditions |
| citations / 引用核查 | Citation identity, scientific support and Bib consistency | [Citations](citations.md) | Identity and support verified separately, or explicitly pending |
| math / 数学与符号 | Definitions, operations, quantifiers and boundary cases | [Math](math.md) | Equation and its actual operational meaning agree |
| blind / 双盲与复现 | Anonymity and reproducible protocol | [Reproducibility](blind.md) | Applicable anonymity checks and actual run specification |
| venue / 投稿规则 | Exact year, track and submission-stage requirements | [Venue](venue.md) | Applicable primary rule plus observed artifact, not a remembered checklist |
| latex / LaTeX 终检 | Source integrity, compilation and PDF checks | [LaTeX](latex.md) | Compile and visual checks recorded separately |

## Three Zhihu Modules Are Specialist Passes, Not Replacements

- `zhihu-paper-structure` advises **writing** on the problem, contribution ownership and section outline. **claims** verifies whether that outline is scientifically supportable; **review** tests whether a reader can recover it. It does not invent new method components.
- `zhihu-paper-readability` advises **writing** on logical relations, defensive claim strength, comprehension delay and information density. **math** owns missing mathematical definitions; **citations** owns reference truth, not the language pass.
- `paper-rebuttal` advises **review** on legitimate counterevidence, and helps **writing** prepare a response when requested. It does not automatically produce a rebuttal after every paragraph or close an experiment gap with persuasive wording.
- `writing-ai-paper` is the final alignment pass, not a second independent source of measurements or venue rules. Figure Skills apply to figure tasks, not every prose edit.

## One Issue, One Evidence State

Carry the existing comment ID across modules. Record: exact quote/file, author's intended claim, issue type, strongest defense, supporting and contrary evidence, remedy, effective diff, verification and remaining gap. Group duplicates but retain their IDs. Do not generate another comment merely because several modules notice the same defect.

Use four different decisions: **text repair**, **evidence required**, **criticism rebutted**, **external verification required**. A repair can narrow a claim while its missing-experiment issue remains open. Source saved, PDF compiled, visual checked and scientific concern resolved are separate states. Review mode returns findings, not patches; explicit revision mode may return exact-source changes. Neither a Markdown worksheet nor a model statement grants permission to run experiments or submit a paper.
