import React from "react";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { MemoirProvider } from "../src/context";
import { palette } from "../src/ui";
export default function Layout() {
  return (
    <SafeAreaProvider>
      <MemoirProvider>
        <StatusBar style="dark" />
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: palette.paper },
            headerTintColor: palette.ink,
            headerShadowVisible: false,
            contentStyle: { backgroundColor: palette.paper },
            headerBackButtonDisplayMode: "minimal",
          }}
        >
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="draft" options={{ title: "Memoir" }} />
          <Stack.Screen name="collection" options={{ title: "Memoir" }} />
          <Stack.Screen name="places" options={{ title: "Memoir" }} />
          <Stack.Screen name="people" options={{ title: "Memoir" }} />
          <Stack.Screen name="timeline" options={{ title: "Memoir" }} />
          <Stack.Screen name="source" options={{ title: "Memoir" }} />
          <Stack.Screen name="sign-in" options={{ title: "Memoir" }} />
          <Stack.Screen name="profile" options={{ title: "Memoir" }} />
          <Stack.Screen name="privacy" options={{ title: "Memoir" }} />
          <Stack.Screen
            name="record"
            options={{ title: "Memoir", presentation: "modal" }}
          />
          <Stack.Screen name="export" options={{ title: "Memoir" }} />
        </Stack>
      </MemoirProvider>
    </SafeAreaProvider>
  );
}
