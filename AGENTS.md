# Prompt governance

Before creating or changing any model prompt, including shared components, read
the [versioned prompt workflow](README.md#versioned-prompt-artifacts).

Langfuse is the source of truth: publish changes as a new prompt version, then
export that version to the corresponding repository `.md` and `.langfuse.json`
receipt. Keep both exports together and verify their pinned version and content
against Langfuse with the documented prompt check before handoff.
