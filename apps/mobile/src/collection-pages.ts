import { useEffect, useRef } from "react";
import { useMemoir } from "./context";
import { useResource, useScopedState } from "./resource";

/** Explicit page reads preserve unseen selections and reject changed roots. */
export function useCollectionPages(enabled = true) {
  const { api, projectId, session, t } = useMemoir();
  const resource = useResource(
    () =>
      enabled
        ? api!.collection(projectId)
        : Promise.resolve({
            revision: 0,
            periods: {},
            ready: false,
            sources: [],
          }),
    [projectId, enabled],
  );
  const [loadingMore, setLoadingMore] = useScopedState(false);
  const [pageError, setPageError] = useScopedState("");
  const scope = JSON.stringify([session?.user.id, projectId]);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const currentPage = useRef(resource.value);
  currentPage.current = resource.value;
  const inFlight = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  async function loadMore() {
    const before = resource.value;
    if (!before?.next_cursor || inFlight.current) return;
    const cursor = before.next_cursor;
    inFlight.current = true;
    setLoadingMore(true);
    setPageError("");
    try {
      const page = await api!.collectionPage(projectId, cursor);
      if (!alive.current || currentScope.current !== scope) return;
      if (
        currentPage.current?.next_cursor !== cursor ||
        currentPage.current.revision !== before.revision ||
        page.revision !== before.revision ||
        page.source_fingerprint !== before.source_fingerprint
      ) {
        setPageError(t("revisionConflict"));
        return;
      }
      const ids = new Set((before.sources ?? []).map((source) => source.id));
      resource.setValue({
        ...before,
        complete: page.complete,
        next_cursor: page.next_cursor,
        sources: [
          ...(before.sources ?? []),
          ...(page.sources ?? []).filter((source) => !ids.has(source.id)),
        ],
      });
    } catch {
      if (alive.current && currentScope.current === scope)
        setPageError(t("revisionConflict"));
    } finally {
      inFlight.current = false;
      if (alive.current && currentScope.current === scope)
        setLoadingMore(false);
    }
  }
  return { ...resource, loadMore, loadingMore, pageError };
}
