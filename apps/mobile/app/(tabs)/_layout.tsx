import React from "react";
import { Tabs } from "expo-router";
import Ionicons from "@expo/vector-icons/Ionicons";
import { useMemoir } from "../../src/context";
import { palette, styles } from "../../src/ui";
export default function TabLayout() {
  const { t } = useMemoir();
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: palette.paper },
        headerTintColor: palette.ink,
        headerShadowVisible: false,
        tabBarActiveTintColor: palette.green,
        tabBarInactiveTintColor: palette.muted,
        tabBarStyle: styles.tabBar,
        tabBarLabelStyle: styles.tabLabel,
        tabBarHideOnKeyboard: true,
      }}
    >
      {(["index", "story", "library", "account"] as const).map((name, i) => (
        <Tabs.Screen
          key={name}
          name={name}
          options={{
            title: t((["talk", "story", "library", "account"] as const)[i]!),
            tabBarIcon: ({ color, size }) => (
              <Ionicons
                name={
                  (
                    [
                      "chatbubble-outline",
                      "book-outline",
                      "albums-outline",
                      "person-circle-outline",
                    ] as const
                  )[i]!
                }
                color={color}
                size={size}
              />
            ),
          }}
        />
      ))}
    </Tabs>
  );
}
