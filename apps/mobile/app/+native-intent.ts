/** Bound and validate native URLs before Expo Router's query decoder runs.
 * This is a guard for GHSA-vcc3-ghjq-m6fr, not an upstream package patch.
 * Authentication/ownership validation remains in the auth and API boundaries.
 */
export function redirectSystemPath({
  path,
}: {
  path: string;
  initial: boolean;
}): string {
  if (
    typeof path !== "string" ||
    path.length > 4096 ||
    /[\u0000-\u0020\\]/.test(path)
  )
    return "/";
  try {
    const decoded = decodeURIComponent(path);
    if (/[\u0000-\u001f\\]/.test(decoded)) return "/";
    return path;
  } catch {
    return "/";
  }
}
