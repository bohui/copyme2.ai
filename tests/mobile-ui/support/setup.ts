// These tests render actual screens and native host primitives. Only external
// boundaries are replaced: no browser, device, credentials or live backend.
jest.mock("../../../apps/mobile/src/context", () => ({ useMemoir: jest.fn() }));
jest.mock("expo-router", () => ({
  router: { push: jest.fn(), replace: jest.fn(), back: jest.fn() },
  useLocalSearchParams: jest.fn(() => ({})),
}));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("@expo/vector-icons/Ionicons", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 47, right: 0, bottom: 34, left: 0 }),
}));
jest.mock("../../../apps/mobile/src/platform/use-recorder", () => ({
  useForegroundRecorder: jest.fn(),
}));
jest.mock("../../../apps/mobile/src/platform/use-reply-audio", () => ({
  useReplyAudio: jest.fn(),
}));

import { useReplyAudio } from "../../../apps/mobile/src/platform/use-reply-audio";

beforeEach(() => {
  jest.mocked(useReplyAudio).mockReturnValue({
    play: jest.fn(async () => undefined),
    stop: jest.fn(async () => undefined),
    active: null,
    busy: false,
    failed: false,
  });
  jest.spyOn(globalThis, "fetch").mockImplementation(async () => {
    throw new Error("Live network is forbidden in the native screen fixtures");
  });
});
