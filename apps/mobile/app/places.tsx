import React, { useEffect, useRef } from "react";
import { Image, Text, View, Linking } from "react-native";
import { useMemoir } from "../src/context";
import { useScopedState, useResource, records, string } from "../src/resource";
import type { PlacePhoto } from "@memoir/contracts";
import { Body, Button, Card, Heading, Notice, Screen, styles } from "../src/ui";
function safeUrl(value: unknown) {
  try {
    const url = new URL(string(value));
    return url.protocol === "https:" && !url.username && !url.password
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}
export default function Places() {
  const { api, projectId, session, t } = useMemoir();
  const r = useResource(() => api!.workspaceProfile(), [projectId]);
  const [selected, setSelected] = useScopedState<Record<
    string,
    unknown
  > | null>(null);
  const [photos, setPhotos] = useScopedState<PlacePhoto[]>([]);
  const [cursor, setCursor] = useScopedState<string | null>(null);
  const [busy, setBusy] = useScopedState(false);
  const [error, setError] = useScopedState("");
  const scope = JSON.stringify([session?.user.id, projectId]);
  const request = useRef({
    scope,
    api,
    generation: 0,
    placeKey: null as string | null,
    cursor: null as string | null,
    busy: false,
  });
  if (request.current.scope !== scope || request.current.api !== api) {
    request.current = {
      scope,
      api,
      generation: request.current.generation + 1,
      placeKey: null,
      cursor: null,
      busy: false,
    };
  }
  useEffect(
    () => () => {
      request.current.generation++;
    },
    [],
  );
  const places = records(r.value?.memory_places);
  async function load(place: Record<string, unknown>, more = false) {
    if (
      !api ||
      !session ||
      request.current.scope !== scope ||
      request.current.api !== api
    )
      return;
    const placeKey = JSON.stringify([
      place.id,
      place.place,
      place.period,
      place.latitude,
      place.longitude,
    ]);
    const current = request.current;
    // Use a synchronous guard: two taps can arrive before disabled rerenders.
    if (
      more
        ? current.busy || current.placeKey !== placeKey || !current.cursor
        : current.busy && current.placeKey === placeKey
    )
      return;
    const pageCursor = more ? current.cursor : null;
    const generation = current.generation + 1;
    request.current = {
      scope,
      api,
      generation,
      placeKey,
      cursor: pageCursor,
      busy: true,
    };
    const isCurrent = () =>
      request.current.scope === scope &&
      request.current.api === api &&
      request.current.generation === generation &&
      request.current.placeKey === placeKey;
    setBusy(true);
    setError("");
    setSelected(place);
    if (!more) {
      setPhotos([]);
      setCursor(null);
    }
    try {
      const page = await api.placePhotos(projectId, {
        place: string(place.place),
        period: string(place.period),
        ...(typeof place.latitude === "number" &&
        typeof place.longitude === "number"
          ? { latitude: place.latitude, longitude: place.longitude }
          : {}),
        ...(pageCursor ? { cursor: pageCursor } : {}),
      });
      // A selection can change and return to the same place while this awaits.
      // Fence success, failure and loading completion by the admitted request.
      if (!isCurrent()) return;
      setPhotos((previous) =>
        more ? [...previous, ...page.items] : page.items,
      );
      request.current.cursor = page.next_cursor ?? null;
      setCursor(page.next_cursor ?? null);
    } catch {
      if (isCurrent()) setError(t("error"));
    } finally {
      if (isCurrent()) {
        request.current.busy = false;
        setBusy(false);
      }
    }
  }
  return (
    <Screen>
      <Heading title={t("places")} subtitle={t("placesBody")} />
      {r.error && <Notice text={r.error} />}{" "}
      {r.loading && <Body>{t("loading")}</Body>}
      {!r.loading && !places.length && <Body>{t("noPlaces")}</Body>}
      {places.map((place, i) => (
        <Card key={string(place.id, String(i))}>
          <Text style={styles.h2}>{string(place.place)}</Text>
          <Text style={styles.small}>
            {string(place.period)} · {string(place.life_stage)}
          </Text>
          <Button
            title={t("photos")}
            secondary
            onPress={() => void load(place)}
          />
        </Card>
      ))}
      {selected && (
        <>
          <Heading title={string(selected.place)} subtitle={t("historical")} />
          {busy && <Body>{t("loading")}</Body>}
          {error && <Notice text={error} />}{" "}
          {photos.map((photo, i) => {
            const image = safeUrl(
              photo.thumbnail_url ?? photo.image_url ?? photo.url,
            );
            const source = safeUrl(photo.source_url);
            return (
              <Card key={photo.id ?? photo.asset_id ?? String(i)}>
                {image && (
                  <Image
                    source={{ uri: image }}
                    accessibilityLabel={photo.title ?? t("historical")}
                    style={{ height: 210, width: "100%", borderRadius: 12 }}
                  />
                )}
                <Text style={styles.h3}>{photo.title}</Text>
                <Text style={styles.small}>{photo.date_expression}</Text>
                {photo.search_fallback && photo.search_fallback !== "none" && (
                  <Text style={styles.small}>
                    {t(
                      photo.search_fallback === "gps_time"
                        ? "otherPeriod"
                        : "distanceUnknown",
                    )}
                  </Text>
                )}
                <Text style={styles.small}>
                  {photo.attribution} {photo.license}
                </Text>
                {source && (
                  <Button
                    title={t("rights")}
                    secondary
                    onPress={() => void Linking.openURL(source)}
                  />
                )}
              </Card>
            );
          })}
          {!busy && !photos.length && <Body>{t("unavailable")}</Body>}
          {cursor && (
            <Button
              title={t("more")}
              disabled={busy}
              onPress={() => void load(selected, true)}
            />
          )}
          <View style={styles.divider} />
        </>
      )}
    </Screen>
  );
}
