# Dependency security gate

Audit date: 7 October 2026. After the scoped UUID fix, the SDK 57 lockfile reports **53 affected dependency nodes (45 high, 8 moderate)** with `npm audit --omit=dev --json`, and **54 nodes (46 high, 8 moderate)** including development dependencies. Four advisory roots remain unresolved. These are dependency-propagation counts, not distinct vulnerabilities or proof of runtime exploitability. Prior snapshots reported 61 and 102 nodes; use the command scope and current lockfile rather than comparing totals as distinct security defects. The audit is not clean.

| Root dependency      | Installed version | Path / exposure                      | Current disposition                                                                                                                   |
| -------------------- | ----------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| braces               | 3.0.3             | micromatch in Metro/Jest and tooling | No patched release listed; do not expose the development bundler to untrusted clients or process untrusted glob patterns              |
| decode-uri-component | 0.2.2             | query-string 7 in Expo Router         | Native system paths are bounded and rejected on malformed percent encoding before router parsing; remains an upstream dependency gate |
| node-forge           | 1.4.0             | Expo CLI/code-signing tooling        | No patched release listed; affected certificate-verification workflow requires separate disposition before signing/distribution                                      |
| sprintf-js           | 1.0.3             | argparse in tooling                  | No patched release listed in registry at check time; no user-controlled format strings are introduced                                 |
| uuid                 | 11.1.1             | xcode project tooling                | Resolved by scoped xcode 3.0.1 override; patched CommonJS v4 is covered by an actual xcode ID-generation regression                                                |

The resolved UUID advisory row is retained for traceability. The repository's application code uses Expo Crypto UUID generation and native URL parsing; it does not call the vulnerable uuid buffer API, node-forge signature verification, sprintf formatter or braces functions. This source observation is not a complete reachability/security certification of third-party packages. SDK dependencies include their toolchains under production dependency classifications, so `--omit=dev` alone does not establish native runtime exploitability.

The documented workaround for decode-uri-component is to limit input. `app/+native-intent.ts` applies a 4,096-character bound and rejects malformed decoding before Expo Router handles native URLs. Deterministic fixtures cover both cold and warm intent entry. Actual device link validation remains required. The web bundle is a local synthetic UI preview; it is not approved for public hosting or authenticated production use.

Do not run `npm audit fix --force`: its suggested Expo 44/RN 0.72 downgrades violate the verified SDK 57 compatibility matrix. decode-uri-component 0.5.0 is ESM-only, while query-string 7.1.3 requires a CommonJS callable; a blind override fails parsing. The latest available SDK 57 Router (57.0.25) still uses query-string 7.1.3. A wider SDK migration requires separate compatibility work. sprintf-js 1.1.3 also remains affected, so merely updating its installed 1.0.3 does not fix the advisory. Security review must resolve or explicitly assess these advisories before distribution. This branch does not claim a clean dependency audit or release approval.

Primary sources:

- https://github.com/advisories/GHSA-vfj7-8cjw-p6xm
- https://github.com/advisories/GHSA-vcc3-ghjq-m6fr
- https://github.com/advisories/GHSA-86w9-cpqp-85rv
- https://github.com/advisories/GHSA-hp3w-g68c-fv3c
- https://github.com/advisories/GHSA-w5hq-g745-h8pq
- https://docs.expo.dev/router/advanced/native-intent/

## Independent cloud security review

The reviewed native source configuration has microphone permission present, camera blocked, background audio services/capability absent, Android backup disabled, iOS arbitrary network loads disabled, SQLCipher enabled and no Face ID permission. Native configuration introspection and 27 auth, secure-storage, vault and intent tests pass. These are source/configuration checks, not proof of compiled manifests or actual storage/permission behavior on a device.

Installed SDK cold/warm linking code invokes the native-intent guard. Sixteen adversarial/valid URL cases were exercised through the guard and the installed Expo extraction/query-parser functions with zero calls to the vulnerable decoder; the selected parser uses URLSearchParams. This supports the inspected native ingress mitigation only. Alternative routing, future SDK paths, public web deployment and actual device delivery are not certified. The vulnerable package remains installed.

The reviewer found no known cloud-fixable P1/P2 source-integration issue on the inspected code. This is a bounded risk assessment, not a clean-audit claim, blanket dependency clearance or release approval. Keep development tooling isolated from untrusted clients, glob patterns and format strings; do not use the affected signing/certificate workflows until separately reviewed. Reassess when dependencies, routing, tooling exposure or deployment scope change. A zero-alert dependency policy, if required, is not satisfied.

## Scoped UUID fix and source-integration controls

The workspace explicitly declares its existing xcode 3.0.1 build-test dependency at the root and overrides only that package's UUID dependency to 11.1.1. Without the direct root build-test dependency, npm's workspace-link resolution retained UUID 7 despite the override. The regenerated lock changes only root metadata and the UUID package entry; no unrelated dependency version is changed and no global package-manager version is modified.

The new security regression first failed against UUID 7, then passed using patched UUID 11.1.1 through the real xcode `generateUuid` caller. It verifies 1,000 correctly formatted distinct project IDs. A second committed regression exercises the 16 guarded URL cases through installed Expo parser helpers. Both are part of `npm run check:mobile`; they do not replace native acceptance.

Independent review recommends source-only integration for trusted local testing, subject to passing the changed-tree checks and these controls:

- No automatic signing, deployment, distribution or live canary from integration
- No public Metro/dev-server exposure or public hosting of the synthetic web preview
- Preserve native URL bounds, malformed-encoding rejection, HTTPS enforcement and security configuration assertions
- Keep the four unresolved advisory roots and device/security follow-ups visible; no zero-alert policy waiver is implied

Signing/certificate workflows, distribution and public deployment remain blocked pending separate security assessment.
