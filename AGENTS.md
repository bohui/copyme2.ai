# Prompt governance

Before creating or changing any model prompt, including shared components, read
the [versioned prompt workflow](README.md#versioned-prompt-artifacts).

Review prompt Markdown in Git and merge it to `main` before publishing. Do not
create Langfuse versions from feature branches. After pulling `main`, the
installed Git hook runs `make prompt-sync`'s publisher, which creates a version
only for changed content and refreshes the matching `.langfuse.json` receipt.
Use `make prompt-sync` to retry and `make prompt-check` to verify published pins.
Review and commit generated receipt updates; never invent a published version.
