/** Real React Native component rendering; hardware, network and auth are fixtures. */
module.exports = {
  preset: "@react-native/jest-preset",
  haste: {
    defaultPlatform:
      process.env.MEMOIR_TEST_PLATFORM === "android" ? "android" : "ios",
    platforms: ["android", "ios", "native"],
  },
  rootDir: "../..",
  roots: ["<rootDir>/tests/mobile-ui"],
  testMatch: ["**/*.test.tsx"],
  setupFilesAfterEnv: ["<rootDir>/tests/mobile-ui/support/setup.ts"],
  clearMocks: true,
  restoreMocks: true,
  transform: {
    "^.+\\.[jt]sx?$": [
      "babel-jest",
      {
        presets: ["babel-preset-expo"],
        plugins: [
          require.resolve("../../tests/mobile-ui/support/dynamic-import.cjs"),
        ],
      },
    ],
  },
  testTimeout: 10000,
  collectCoverageFrom: ["apps/mobile/app/**/*.tsx", "apps/mobile/src/ui.tsx"],
};
