/** Explicit OS share action. Files stay app-private until the user selects a target. */
export async function shareSourceExport(value: unknown): Promise<void> {
  const [{ File, Paths }, sharing, crypto, { Platform }] = await Promise.all([
    import("expo-file-system"),
    import("expo-sharing"),
    import("expo-crypto"),
    import("react-native"),
  ]);
  if (Platform.OS === "web" || !(await sharing.isAvailableAsync()))
    throw new Error("Native sharing is unavailable");
  const file = new File(
    Paths.cache,
    `memoir-sources-${crypto.randomUUID()}.json`,
  );
  try {
    file.write(JSON.stringify(value, null, 2));
    await sharing.shareAsync(file.uri, {
      mimeType: "application/json",
      UTI: "public.json",
      dialogTitle: "Memoir sources",
    });
  } finally {
    if (file.exists) file.delete();
  }
}
