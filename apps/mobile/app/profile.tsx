import React, { useEffect } from "react";
import { useMemoir } from "../src/context";
import { useScopedState, useResource } from "../src/resource";
import { Button, Field, Heading, Notice, Screen } from "../src/ui";
export default function Profile() {
  const { api, t } = useMemoir();
  const r = useResource(() => api!.profile());
  const [name, setName] = useScopedState("");
  const [place, setPlace] = useScopedState("");
  const [year, setYear] = useScopedState("");
  const [childhood, setChildhood] = useScopedState("");
  const [notice, setNotice] = useScopedState("");
  useEffect(() => {
    if (r.value) {
      setName(r.value.name ?? "");
      setPlace(r.value.birth_place ?? "");
      setYear(String(r.value.birth_year ?? ""));
      setChildhood(r.value.childhood_place ?? "");
    }
  }, [r.value]);
  async function save() {
    const birth = year.trim() ? Number(year) : null;
    if (
      birth !== null &&
      (!Number.isInteger(birth) ||
        birth < 1800 ||
        birth > new Date().getFullYear())
    ) {
      setNotice(t("birthyear"));
      return;
    }
    try {
      await api!.updateProfile({
        name,
        birth_place: place,
        birth_year: birth,
        childhood_place: childhood,
      });
      setNotice(t("saved"));
    } catch {
      setNotice(t("error"));
    }
  }
  return (
    <Screen>
      <Heading title={t("profile")} />
      {r.error && <Notice text={r.error} />}
      <Field
        label={t("name")}
        value={name}
        onChangeText={setName}
        maxLength={120}
      />
      <Field
        label={t("birthyear")}
        value={year}
        onChangeText={setYear}
        keyboardType="number-pad"
        maxLength={4}
      />
      <Field
        label={t("birthplace")}
        value={place}
        onChangeText={setPlace}
        maxLength={160}
      />
      <Field
        label={t("childhood")}
        value={childhood}
        onChangeText={setChildhood}
        maxLength={160}
      />
      {notice && <Notice text={notice} />}
      <Button
        title={t("save")}
        disabled={!r.value}
        onPress={() => void save()}
      />
    </Screen>
  );
}
