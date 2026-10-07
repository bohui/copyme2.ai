/** Integrates the real provider, auth service, API client, and fixture vault. */
module.exports = {
  preset: "@react-native/jest-preset",
  rootDir: "../..",
  roots: ["<rootDir>/tests/mobile-integration"],
  testMatch: ["**/*.test.tsx"],
  setupFilesAfterEnv: ["<rootDir>/tests/mobile-integration/support/runtime.ts"],
  clearMocks: true,
  restoreMocks: true,
  transform: {
    "^.+\\.[jt]sx?$": [
      "babel-jest",
      {
        presets: ["babel-preset-expo"],
        plugins: [
          require.resolve("../../tests/mobile-integration/support/dynamic-import.cjs"),
        ],
      },
    ],
  },
  testTimeout: 10000,
};
