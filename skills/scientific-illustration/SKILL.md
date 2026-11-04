---
name: scientific-illustration
description: Create editable, publication-oriented scientific illustrations and revise them from comments. Use for diagram assets and scientific figure rendering, not numerical data synthesis.
---

# Scientific Illustration

Sources: the author's supplied Scientific Illustrator prompt and [Leey21/awesome-ai-research-writing](https://github.com/Leey21/awesome-ai-research-writing#论文架构图), accessed 2026-10-19. Read [the author template](references/illustrator-prompt.md) when generating a diagram. Preserve its intent; recognizable institutional styling does not imply endorsement.

First validate scientific content, then design basic components, then refine composition. Create an editable vector source with a matching publication PDF. Prefer deterministic text rendering for labels. Do not execute arbitrary model-produced scripts or accept active SVG content, remote assets, HTML, fonts or external URLs.

Use a common typography, role palette, spacing and arrow vocabulary across all figures. A diagram is not improved by adding modules absent from the method. Motivation and novelty must remain legible without an ornate caption. Avoid decorative 3D, photos, excessive equations, long labels and low-contrast fills.

After rendering inspect the actual PDF at its intended print size, plus grayscale where useful. Check missing glyphs, label overflow, clipped edges, font embedding and caption agreement. A successful compiler run is not visual verification. Preserve source data and editable geometry with each revision.

When comments request changes, distinguish scientific changes from layout changes. Save successive drafts, keep previous PDFs reproducible and apply only explicitly approved current-revision changes. Record unsupported requests as pending, not complete. Use the economical configured native GPT by default; Astra is opt-in. Do not call image services, Claude, Opus or Fable as a hidden fallback.
