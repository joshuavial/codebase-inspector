import type { RemoteRef } from "./switcher";

/** The only git commands the switcher adds. Fetch is user-started. Listing remotes is a read. */
export const FETCH_ARGV = ["fetch", "--prune"] as const;
export const REMOTES_ARGV = ["for-each-ref", "--format=%(refname:short)%00%(objectname)", "refs/remotes"] as const;

const ALLOWED = [FETCH_ARGV, REMOTES_ARGV];

export function assertRemoteArgv(args: readonly string[]) {
  const ok = ALLOWED.some((expected) => expected.length === args.length && expected.every((part, index) => part === args[index]));
  if (!ok) throw new Error(`refusing git ${args.join(" ")}`);
}

/** `git for-each-ref` of refs/remotes. `origin/HEAD` is a symbolic default, not a branch. */
export function parseRemoteRefs(text: string): RemoteRef[] {
  const refs: RemoteRef[] = [];
  for (const line of text.split("\n")) {
    if (!line) continue;
    const [name, head] = line.split("\0");
    if (!name || !head || name.endsWith("/HEAD")) continue;
    refs.push({ name, head });
  }
  refs.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  return refs;
}
