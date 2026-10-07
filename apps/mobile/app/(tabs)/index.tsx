import React, { useRef, useState } from "react";
import {
  Alert,
  FlatList,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  Text,
  TextInput,
  View,
} from "react-native";
import { router } from "expo-router";
import Ionicons from "@expo/vector-icons/Ionicons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useReplyAudio } from "../../src/platform/use-reply-audio";
import { useMemoir, type ChatMessage } from "../../src/context";
import {
  Body,
  Button,
  Card,
  Check,
  Heading,
  Notice,
  Screen,
  palette,
  styles,
} from "../../src/ui";
export default function Talk() {
  const m = useMemoir();
  const { t } = m;
  const speech = useReplyAudio(m.api, m.session?.user.id);
  const [consent, setConsent] = useState(false);
  const [starting, setStarting] = useState(false);
  const [switcher, setSwitcher] = useState(false);
  const insets = useSafeAreaInsets();
  const list = useRef<FlatList<ChatMessage>>(null);
  const followLatest = useRef(true);
  const projectChoices = [
    ...new Set([
      ...m.projects.map((project) => project.project_id),
      ...m.localProjectIds,
      ...(m.projectId ? [m.projectId] : []),
    ]),
  ];
  const hasPending = m.pending.some(
    (item) => item.projectId === m.projectId && item.state !== "committed",
  );
  const busy =
    m.identityBusy ||
    m.loading ||
    !m.vault ||
    !m.projectId ||
    hasPending ||
    (!!m.active &&
      !m.active.state.committed &&
      !["uncertain", "rejected", "paused"].includes(m.active.state.phase));
  function discard(item: NonNullable<typeof m.active>["item"]) {
    Alert.alert(t("discard"), t("discardWarning"), [
      { text: t("cancel"), style: "cancel" },
      {
        text: t("discard"),
        style: "destructive",
        onPress: () => void m.discard(item),
      },
    ]);
  }
  if (!m.session)
    return (
      <Screen>
        <Heading title={t("hello")} eyebrow="MEMOIR" subtitle={t("welcome")} />
        <Image
          source={
            m.locale === "zh-CN"
              ? require("../../assets/mira-zh.png")
              : require("../../assets/mira-en.png")
          }
          style={{
            height: 190,
            width: 190,
            alignSelf: "center",
            borderRadius: 95,
          }}
          accessibilityLabel="Mira"
        />
        <Body>{t("welcomeBody")}</Body>
        {m.loading ? (
          <Body>{t("loading")}</Body>
        ) : !m.configured ? (
          <Notice text={t("configureBody")} />
        ) : (
          <>
            <Card>
              <Text style={styles.small}>{t("aiNotice")}</Text>
              <Check
                label={t("consent")}
                checked={consent}
                onPress={() => setConsent(!consent)}
              />
            </Card>
            <Button
              title={t("begin")}
              disabled={!consent || starting}
              loading={starting}
              onPress={() => {
                setStarting(true);
                void m.begin().finally(() => setStarting(false));
              }}
            />
            <Button
              title={t("signIn")}
              secondary
              disabled={starting}
              onPress={() => router.push("/sign-in")}
            />
            <Text style={styles.small}>{t("guestNotice")}</Text>
          </>
        )}
        {m.error && <Notice text={m.error} />}
        <Button
          title={m.locale === "en-AU" ? "简体中文" : "English"}
          secondary
          onPress={() =>
            void m.setLocale(m.locale === "en-AU" ? "zh-CN" : "en-AU")
          }
        />
      </Screen>
    );
  const active = m.active;
  const visibleActive =
    active && !active.state.contentUnavailable && !active.state.replayBlocked
      ? active
      : null;
  const currentMessages = [
    ...m.messages,
    ...(visibleActive
      ? [
          {
            id: visibleActive.item.operationId + "-pending-user",
            role: "user" as const,
            text: visibleActive.item.command.text,
          },
          ...(visibleActive.state.reply
            ? [
                {
                  id: visibleActive.item.operationId + "-pending-assistant",
                  role: "assistant" as const,
                  text: visibleActive.state.reply,
                },
              ]
            : []),
        ]
      : []),
  ];
  return (
    <KeyboardAvoidingView
      style={styles.screen}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={100}
    >
      {m.fixture && (
        <Text
          style={[
            styles.eyebrow,
            { padding: 8, textAlign: "center", backgroundColor: palette.sage },
          ]}
        >
          {t("fixture")}
        </Text>
      )}
      <View style={{ paddingHorizontal: 20, paddingVertical: 12, gap: 10 }}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={t("chooseStory")}
          onPress={() => setSwitcher(!switcher)}
          style={styles.row}
        >
          <Image
            source={
              m.locale === "zh-CN"
                ? require("../../assets/mira-zh.png")
                : require("../../assets/mira-en.png")
            }
            style={{ width: 44, height: 44, borderRadius: 22 }}
          />
          <View style={styles.grow}>
            <Text style={styles.h3}>Mira</Text>
            <Text style={styles.small}>{t("private")}</Text>
          </View>
          <Ionicons name="chevron-down" size={20} color={palette.green} />
        </Pressable>
        {switcher && (
          <Card>
            {projectChoices.map((id, index) => (
              <Button
                key={id}
                title={`${t("story")} ${index + 1}${m.projects.some((project) => project.project_id === id) ? "" : ` · ${t("local")}`}`}
                secondary
                onPress={() => {
                  void m.selectProject(id);
                  setSwitcher(false);
                }}
              />
            ))}
            <Button
              title={t("newStory")}
              onPress={() => {
                void m.newProject();
                setSwitcher(false);
              }}
            />
          </Card>
        )}
      </View>
      <FlatList
        ref={list}
        maintainVisibleContentPosition={{ minIndexForVisible: 0 }}
        onContentSizeChange={() => {
          if (followLatest.current)
            list.current?.scrollToEnd({ animated: false });
        }}
        onScroll={({ nativeEvent }) => {
          followLatest.current =
            nativeEvent.contentSize.height -
              nativeEvent.contentOffset.y -
              nativeEvent.layoutMeasurement.height <
            100;
        }}
        scrollEventThrottle={100}
        ListHeaderComponent={
          m.historyCursor ? (
            <Button
              title={t("earlier")}
              secondary
              onPress={() => void m.loadEarlier()}
            />
          ) : null
        }
        data={currentMessages}
        keyExtractor={(item) => item.id}
        contentContainerStyle={{ padding: 20, gap: 18, flexGrow: 1 }}
        keyboardShouldPersistTaps="handled"
        renderItem={({ item }) => (
          <View
            style={{
              alignSelf: item.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "94%",
              gap: 6,
            }}
          >
            <Text style={[styles.small, { marginHorizontal: 3 }]}>
              {item.role === "user"
                ? (m.session?.user.email ?? t("guest"))
                : "Mira"}
            </Text>
            <View
              style={{
                padding: 17,
                borderRadius: 22,
                backgroundColor:
                  item.role === "user" ? palette.green : palette.card,
                borderWidth: item.role === "user" ? 0 : 1,
                borderColor: palette.line,
              }}
            >
              <Text
                selectable
                style={[
                  styles.body,
                  { color: item.role === "user" ? palette.card : palette.ink },
                ]}
              >
                {item.text}
              </Text>
            </View>
            {item.role === "assistant" && item.text.length <= 4096 && (
              <Button
                title={t(speech.active === item.id ? "stopPlayback" : "listen")}
                secondary
                disabled={speech.busy && speech.active !== item.id}
                icon={
                  speech.active === item.id ? "stop" : "volume-high-outline"
                }
                onPress={() => void speech.play(item.id, item.text, m.locale)}
              />
            )}
          </View>
        )}
        ListEmptyComponent={
          <View style={[styles.empty, { flex: 1, justifyContent: "center" }]}>
            <Text style={styles.eyebrow}>{t("prompt")}</Text>
            <Text style={styles.title}>{t("emptyTalk")}</Text>
          </View>
        }
      />
      <View
        style={{
          paddingHorizontal: 18,
          paddingBottom: Math.max(12, insets.bottom / 2),
          gap: 10,
        }}
      >
        {m.error && <Notice text={m.error} />}{" "}
        {speech.failed && <Notice text={t("unavailable")} />}
        <View accessibilityLiveRegion="polite">
          {active && (
            <Text style={styles.small}>
              {t(
                active.state.committed
                  ? "saved"
                  : active.state.phase === "receiving"
                    ? "receiving"
                    : active.state.phase === "uncertain"
                      ? "uncertain"
                      : "queued",
              )}
            </Text>
          )}
        </View>
        {m.pending
          .filter(
            (x) =>
              x.projectId === m.projectId &&
              x.operationId !== active?.item.operationId,
          )
          .slice(0, 1)
          .map((item) => (
            <View key={item.operationId} style={{ gap: 8 }}>
              <Button
                title={t("retry")}
                secondary
                onPress={() => void m.retry(item)}
              />
              <Button
                title={t("discard")}
                secondary
                onPress={() => discard(item)}
              />
            </View>
          ))}
        {active &&
          ["uncertain", "paused", "rejected"].includes(active.state.phase) && (
            <View style={{ gap: 8 }}>
              {!active.state.replayBlocked && (
                <Button
                  title={t("retry")}
                  secondary
                  onPress={() => void m.retry(active.item)}
                />
              )}
              <Button
                title={t("discard")}
                secondary
                onPress={() => discard(active.item)}
              />
            </View>
          )}
        <View style={[styles.card, { padding: 10, borderRadius: 24, gap: 6 }]}>
          <TextInput
            accessibilityLabel={t("write")}
            placeholder={t("write")}
            placeholderTextColor={palette.muted}
            value={m.draft}
            onChangeText={(value) => void m.setDraft(value)}
            editable={
              !m.identityBusy && !m.loading && !!m.vault && !!m.projectId
            }
            multiline
            maxLength={100000}
            style={[
              styles.body,
              {
                minHeight: 52,
                maxHeight: 150,
                paddingHorizontal: 8,
                paddingVertical: 10,
              },
            ]}
            textAlignVertical="top"
          />
          <View style={[styles.row, { justifyContent: "space-between" }]}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={t("record")}
              onPress={() => router.push("/record")}
              style={styles.iconButton}
            >
              <Ionicons name="mic-outline" size={24} color={palette.green} />
            </Pressable>
            <Button
              title={t("send")}
              icon="arrow-up"
              disabled={!m.draft.trim() || busy}
              onPress={() => void m.send()}
            />
          </View>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}
