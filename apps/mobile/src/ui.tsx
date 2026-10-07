import React from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type ViewStyle,
} from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";
export const palette = {
  paper: "#f7f2e9",
  card: "#fffdf8",
  ink: "#25302d",
  muted: "#59665f",
  green: "#315f55",
  sage: "#e1eade",
  line: "#d8dbd2",
  coral: "#ab523c",
  gold: "#b88c40",
};
export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.paper },
  content: {
    padding: 22,
    paddingBottom: 32,
    gap: 18,
    width: "100%",
    maxWidth: 740,
    alignSelf: "center",
  },
  eyebrow: {
    color: palette.green,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.5,
    textTransform: "uppercase",
  },
  title: {
    fontFamily: "serif",
    fontSize: 34,
    lineHeight: 41,
    color: palette.ink,
    fontWeight: "600",
  },
  subtitle: { fontSize: 17, lineHeight: 26, color: palette.muted },
  body: { fontSize: 17, lineHeight: 27, color: palette.ink },
  small: { fontSize: 14, lineHeight: 21, color: palette.muted },
  card: {
    backgroundColor: palette.card,
    borderWidth: 1,
    borderColor: palette.line,
    borderRadius: 22,
    padding: 20,
    gap: 12,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 12 },
  grow: { flex: 1 },
  button: {
    minHeight: 50,
    paddingHorizontal: 18,
    paddingVertical: 13,
    borderRadius: 16,
    backgroundColor: palette.green,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 8,
  },
  buttonText: {
    fontSize: 16,
    lineHeight: 23,
    fontWeight: "700",
    color: palette.card,
  },
  secondary: {
    backgroundColor: "transparent",
    borderColor: palette.line,
    borderWidth: 1,
  },
  secondaryText: { color: palette.green },
  input: {
    fontSize: 17,
    lineHeight: 25,
    color: palette.ink,
    borderWidth: 1,
    borderColor: palette.line,
    borderRadius: 14,
    padding: 14,
    minHeight: 52,
    backgroundColor: palette.card,
  },
  error: { backgroundColor: "#fbebe3", borderRadius: 16, padding: 16, gap: 10 },
  pill: {
    alignSelf: "flex-start",
    backgroundColor: palette.sage,
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  divider: { height: 1, backgroundColor: palette.line },
  h2: {
    fontFamily: "serif",
    fontSize: 25,
    lineHeight: 32,
    color: palette.ink,
    fontWeight: "600",
  },
  h3: { fontSize: 19, lineHeight: 27, color: palette.ink, fontWeight: "600" },
  iconButton: {
    height: 50,
    width: 50,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: palette.sage,
  },
  disabled: { opacity: 0.5 },
  empty: { paddingVertical: 26, gap: 15 },
  label: { fontSize: 15, fontWeight: "600", color: palette.ink },
  check: {
    minHeight: 48,
    flexDirection: "row",
    gap: 12,
    alignItems: "center",
    paddingVertical: 8,
  },
  tabBar: {
    backgroundColor: palette.card,
    borderTopColor: palette.line,
    height: 76,
    paddingTop: 8,
    paddingBottom: 12,
  },
  tabLabel: { fontSize: 12, fontWeight: "600" },
});
export function Body({
  children,
  muted = false,
}: {
  children: React.ReactNode;
  muted?: boolean;
}) {
  return <Text style={muted ? styles.subtitle : styles.body}>{children}</Text>;
}
export function Screen({
  children,
  scroll = true,
}: {
  children: React.ReactNode;
  scroll?: boolean;
}) {
  return scroll ? (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      {children}
    </ScrollView>
  ) : (
    <View style={styles.screen}>{children}</View>
  );
}
export function Heading({
  title,
  subtitle,
  eyebrow,
}: {
  title: string;
  subtitle?: string;
  eyebrow?: string;
}) {
  return (
    <View style={{ gap: 9 }}>
      {eyebrow && <Text style={styles.eyebrow}>{eyebrow}</Text>}
      <Text accessibilityRole="header" style={styles.title}>
        {title}
      </Text>
      {subtitle && <Text style={styles.subtitle}>{subtitle}</Text>}
    </View>
  );
}
export function Card({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: ViewStyle;
}) {
  return <View style={[styles.card, style]}>{children}</View>;
}
export function Button({
  title,
  onPress,
  secondary = false,
  disabled = false,
  loading = false,
  icon,
}: {
  title: string;
  onPress: () => void;
  secondary?: boolean;
  disabled?: boolean;
  loading?: boolean;
  icon?: React.ComponentProps<typeof Ionicons>["name"];
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      accessibilityState={{ disabled: disabled || loading, busy: loading }}
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.button,
        secondary && styles.secondary,
        (disabled || loading) && styles.disabled,
        pressed && { opacity: 0.8 },
      ]}
    >
      {loading ? (
        <ActivityIndicator color={secondary ? palette.green : palette.card} />
      ) : (
        icon && (
          <Ionicons
            name={icon}
            size={20}
            color={secondary ? palette.green : palette.card}
          />
        )
      )}
      <Text style={[styles.buttonText, secondary && styles.secondaryText]}>
        {title}
      </Text>
    </Pressable>
  );
}
export function RowLink({
  title,
  body,
  icon,
  onPress,
}: {
  title: string;
  body?: string;
  icon: React.ComponentProps<typeof Ionicons>["name"];
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      onPress={onPress}
      style={[styles.card, styles.row]}
    >
      <View style={styles.iconButton}>
        <Ionicons name={icon} size={24} color={palette.green} />
      </View>
      <View style={[styles.grow, { gap: 4 }]}>
        <Text style={styles.h3}>{title}</Text>
        {body && <Text style={styles.small}>{body}</Text>}
      </View>
      <Ionicons name="chevron-forward" size={20} color={palette.muted} />
    </Pressable>
  );
}
export function Field({ label, ...props }: TextInputProps & { label: string }) {
  return (
    <View style={{ gap: 8 }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={palette.muted}
        style={[
          styles.input,
          props.multiline && { minHeight: 120, textAlignVertical: "top" },
        ]}
        {...props}
      />
    </View>
  );
}
export function Check({
  label,
  checked,
  onPress,
}: {
  label: string;
  checked: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      accessibilityLabel={label}
      onPress={onPress}
      style={styles.check}
    >
      <Ionicons
        name={checked ? "checkbox" : "square-outline"}
        size={25}
        color={palette.green}
      />
      <Text style={[styles.body, styles.grow]}>{label}</Text>
    </Pressable>
  );
}
export function Notice({
  text,
  onRetry,
  retryLabel,
}: {
  text: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <View accessibilityRole="alert" style={styles.error}>
      <Text style={styles.body}>{text}</Text>
      {onRetry && (
        <Button title={retryLabel ?? "Retry"} onPress={onRetry} secondary />
      )}
    </View>
  );
}
