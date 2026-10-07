import type { ExpoConfig } from "expo/config";
const config: ExpoConfig = {
  name: "Memoir",
  slug: "memoir-mobile",
  version: "0.1.0",
  scheme: "memoir",
  icon: "./assets/icon.png",
  userInterfaceStyle: "light",
  orientation: "default",
  ios: {
    bundleIdentifier: "ai.copyme2.memoir.dev",
    supportsTablet: true,
    infoPlist: {
      NSAppTransportSecurity: {
        NSAllowsArbitraryLoads: false,
        NSAllowsLocalNetworking: true,
      },
      NSMicrophoneUsageDescription:
        "Record a memory when you choose to speak. Review it before sending.",
      NSPhotoLibraryUsageDescription:
        "Choose a photograph to add to your private story.",
    },
  },
  android: {
    package: "ai.copyme2.memoir.dev",
    permissions: ["RECORD_AUDIO"],
    allowBackup: false,
  },
  web: { bundler: "metro", output: "single" },
  plugins: [
    "expo-router",
    ["expo-secure-store", { faceIDPermission: false }],
    ["expo-sqlite", { useSQLCipher: true }],
    [
      "expo-audio",
      {
        microphonePermission:
          "Record a memory when you choose to speak. Review it before sending.",
        enableBackgroundRecording: false,
        enableBackgroundPlayback: false,
      },
    ],
    [
      "expo-image-picker",
      {
        photosPermission: "Choose a photograph to add to your private story.",
        cameraPermission: false,
        microphonePermission:
          "Record a memory when you choose to speak. Review it before sending.",
      },
    ],
  ],
  experiments: { typedRoutes: true },
};
export default config;
