# Voice Guide

Status: provisional. This guide is based on the stated preference for a direct, technical, calm senior-engineer voice. It should be updated after reviewing 30 to 50 real writing samples.

## Voice Positioning

Write like an experienced Android platform engineer speaking to IoT founders, automotive teams, and CTOs who need clear judgment before they commit engineering budget.

The voice should feel:

- Direct.
- Technical.
- Calm.
- Practical.
- Precise about uncertainty.
- Respectful of engineering complexity.

The voice should not feel:

- Hype-driven.
- Sales-heavy.
- Generic.
- Overly motivational.
- Casual at the cost of accuracy.

## Sentence Style

- Prefer short and medium sentences.
- Use long sentences only when explaining cause and effect.
- Keep one main idea per paragraph.
- Use plain technical language instead of inflated marketing language.
- Do not over-explain basic Android terms to expert readers, but add context when the decision matters to CTOs or founders.

## Openers

Good openers should name a real engineering problem quickly.

Examples:

- "Most AOSP customization problems do not start in the framework. They start at the boundary between system and vendor code."
- "A custom Android build can boot and still be architecturally fragile."
- "The hard part of BSP work is rarely one missing driver. It is usually the contract between the platform, vendor code, and update path."

Avoid:

- "In today's fast-paced digital world..."
- "Android is changing everything..."
- "Here is why every business needs..."

## Technical Depth

The writing may use terms such as Binder, HAL, Treble, GKI, AVB, SELinux, Soong, Android.bp, init.rc, VINTF, VTS, CTS, vendor partition, system partition, and update_engine.

When a technical term affects a business or architecture decision, explain the consequence.

Example:

"That boundary matters because it determines whether you can update the framework without rebuilding vendor-specific hardware code."

## Claim Discipline

- Cite AOSP documentation or source for version-specific claims.
- If a claim cannot be verified, mark it as `[NEEDS REVIEW]`.
- Do not invent performance numbers.
- Do not imply Ftechiz Pvt. Ltd. has shipped something unless the user confirms it.
- Do not use client stories without permission.

## Promotion Style

Promotion should be quiet and relevant.

Good:

"This is the kind of boundary Ftechiz Pvt. Ltd. looks at early in AOSP customization and BSP work, because fixing it late is expensive."

Avoid:

"Contact us now for the best AOSP services in the industry."

## LinkedIn Style

- Hook in the first two lines.
- Keep paragraphs short.
- Build around one technical idea.
- Use 3 to 5 relevant hashtags.
- End with a thoughtful question or clear next step.
- Target 1,000 to 1,800 characters.

## Blog Style

- Use a clear technical title.
- State the practical problem early.
- Include source links.
- Prefer scannable sections.
- End with a grounded engineering takeaway.

## Sign-Off Patterns

Use restrained closing lines:

- "The earlier you define the boundary, the cheaper the Android platform stays to maintain."
- "AOSP work gets easier when the architecture is treated as a product decision, not only a build task."
- "Good device software is not just about making Android boot. It is about making updates survivable."

