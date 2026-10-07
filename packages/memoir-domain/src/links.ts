export interface DeepLinkOptions {
  httpsHosts: readonly string[];
  scheme: string;
}
export type MemoirDeepLink =
  | { kind: "project"; projectId: string }
  | { kind: "payment-return" }
  | { kind: "auth-callback"; code: string; state?: string };
/** Resolves navigation intent only. Project authorization and paid entitlement
 * must always be fetched. A callback never itself changes session identity. */
export function resolveDeepLink(
  raw: string,
  options: DeepLinkOptions,
): MemoirDeepLink | null {
  if (raw.length > 4096 || /[\u0000-\u0020\\]/.test(raw)) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.username || url.password || url.hash || url.port) return null;
  const custom = url.protocol === `${options.scheme}:`;
  if (
    !custom &&
    (url.protocol !== "https:" ||
      !options.httpsHosts.some((host) => url.hostname === host.toLowerCase()))
  )
    return null;
  let path: string;
  try {
    path = decodeURIComponent(
      (custom ? `/${url.hostname}` : "") + url.pathname,
    );
  } catch {
    return null;
  }
  if (path.includes("..") || path.includes("\\") || path.includes("//"))
    return null;
  const keys = [...url.searchParams.keys()];
  if (keys.some((key) => /token|secret|redirect|url|text|story/i.test(key)))
    return null;
  const project = path.match(
    /^\/projects\/([A-Za-z0-9][A-Za-z0-9_-]{0,127})\/?$/,
  );
  if (project)
    return keys.length ? null : { kind: "project", projectId: project[1]! };
  if (/^\/payment\/return\/?$/.test(path))
    return keys.every((key) => ["session_id", "status"].includes(key))
      ? { kind: "payment-return" }
      : null;
  if (
    /^\/auth\/callback\/?$/.test(path) &&
    keys.every((key) => ["code", "state"].includes(key))
  ) {
    const code = url.searchParams.get("code"),
      state = url.searchParams.get("state");
    if (
      !code ||
      code.length > 2048 ||
      url.searchParams.getAll("code").length !== 1 ||
      url.searchParams.getAll("state").length > 1
    )
      return null;
    return { kind: "auth-callback", code, ...(state ? { state } : {}) };
  }
  return null;
}
export function validateAuthCallback(
  link: MemoirDeepLink | null,
  expected: { state: string; expiresAt: number; consumed: boolean },
  now: number,
): link is Extract<MemoirDeepLink, { kind: "auth-callback" }> {
  return (
    !!link &&
    link.kind === "auth-callback" &&
    !expected.consumed &&
    now < expected.expiresAt &&
    !!expected.state &&
    link.state === expected.state
  );
}
