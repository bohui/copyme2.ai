"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { createBrowserClient } from "@supabase/ssr";
import { restoreLegacyBrowserSession } from "../auth/browser.mjs";
import { mountStoryGameWebpage } from "../client/memoir/story-game.mjs";

export default function StoryGamePage({ projectId }) {
  const t = useTranslations("Memoir.game");
  const root = useRef(null);
  const session = useRef(null);
  const sessionVersion = useRef(0);
  const reload = useRef(null);
  const [page, setPage] = useState(null);
  const [ready, setReady] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [inviteLink, setInviteLink] = useState("");
  const path = `/api/v1/memoir/story-games/${encodeURIComponent(projectId)}`;

  async function api(suffix = "", options = {}, signal) {
    const response = await fetch(path + suffix, {
      ...options, signal, cache: "no-store",
      headers: { "Content-Type": "application/json",
        ...(session.current?.access_token ? { Authorization: `Bearer ${session.current.access_token}` } : {}) },
    });
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  }

  useEffect(() => {
    const controller = new AbortController();
    let subscription, refreshing = false, accepted = false;
    setPage(null); setReady(false); setInviteLink("");
    async function refresh() {
      if (refreshing || controller.signal.aborted) return;
      refreshing = true;
      const version = sessionVersion.current;
      try {
        const token = new URLSearchParams(location.search).get("invite");
        if (token && session.current && !accepted) {
          await api("/invitations/accept", { method: "POST", body: JSON.stringify({ token }) }, controller.signal);
          if (version !== sessionVersion.current) return;
          accepted = true;
          history.replaceState(null, "", location.pathname);
        }
        const value = await api("", {}, controller.signal);
        if (!controller.signal.aborted && version === sessionVersion.current) { setPage(value); setError(""); }
      } catch (failure) {
        if (!controller.signal.aborted && version === sessionVersion.current) {
          setPage(null);
          setError(["401", "403", "404"].includes(failure.message) ? "unavailable" : "retry");
        }
      } finally {
        refreshing = false;
        if (!controller.signal.aborted) setReady(true);
        if (!controller.signal.aborted && version !== sessionVersion.current) queueMicrotask(refresh);
      }
    }
    reload.current = refresh;
    async function start() {
      try {
        const response = await fetch("/api/v1/memoir/agent/config", { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error("config");
        const config = await response.json();
        if (config.supabase_url && config.supabase_publishable_key) {
          const client = createBrowserClient(config.supabase_url, config.supabase_publishable_key, {
            cookieOptions: { path: "/", sameSite: "lax", secure: location.protocol === "https:" },
          });
          session.current = await restoreLegacyBrowserSession(client, config.supabase_url, localStorage);
          setSignedIn(Boolean(session.current));
          subscription = client.auth.onAuthStateChange((_event, value) => {
            sessionVersion.current++;
            session.current = value;
            setSignedIn(Boolean(value));
            setPage(null);
            setInviteLink("");
            queueMicrotask(refresh);
          }).data.subscription;
        }
        await refresh();
      } catch {
        if (!controller.signal.aborted) await refresh();
      }
    }
    void start();
    const timer = setInterval(() => { if (!document.hidden) void refresh(); }, 5000);
    return () => { sessionVersion.current++; controller.abort(); subscription?.unsubscribe(); clearInterval(timer); reload.current = null; };
  }, [projectId]);

  useEffect(() => {
    if (!page || !root.current) return undefined;
    return mountStoryGameWebpage(root.current, page.game,
      key => t(key === "framing" ? "sharedFraming" : key === "title" ? "gamePage" : key),
      () => location.assign("/memoir"));
  }, [page?.game?.package_id, t]);

  async function action(suffix, data) {
    if (busy || !page?.can_manage) return;
    const version = sessionVersion.current;
    setBusy(true); setError("");
    try {
      const value = await api(suffix, { method: suffix === "/visibility" ? "PUT" : "POST",
        body: JSON.stringify({ ...data, expected_revision: page.revision }) });
      if (version !== sessionVersion.current) return;
      if (value.token) setInviteLink(`${location.origin}/memoir/game/${encodeURIComponent(projectId)}?invite=${value.token}`);
      await reload.current?.();
    } catch { setError("retry"); }
    finally { setBusy(false); }
  }

  return <main className="story-game-page">
    <header className="game-page-header"><a href="/memoir">CopyMe2</a><span>{t("gamePage")}</span></header>
    {!ready && <p role="status">{t("loading")}</p>}
    {error && <p role="alert">{t(error)}</p>}
    {!page && ready && !signedIn && <a href="/memoir">{t("signInToPlay")}</a>}
    {page && <>
      {page.example && <p className="game-example-notice">{t("exampleNotice")}</p>}
      <div ref={root} data-project-game />
      {page.can_manage && <section className="game-sharing" aria-label={t("sharing")}>
        <h2>{t("sharing")}</h2>
        <label>{t("whoCanPlay")} <select value={page.visibility} disabled={busy}
          onChange={event => { setInviteLink(""); void action("/visibility", { visibility: event.target.value }); }}>
          <option value="private">{t("privateAccess")}</option>
          <option value="friends">{t("friendsAccess")}</option>
          <option value="public">{t("publicAccess")}</option>
        </select></label>
        <p>{t(page.visibility + "AccessHint")}</p>
        <label>{t("gameLink")}<input readOnly value={typeof location === "undefined" ? "" : location.origin + location.pathname} /></label>
        {page.visibility === "friends" && <>
          <form onSubmit={event => { event.preventDefault(); const email = new FormData(event.currentTarget).get("email"); void action("/invitations", { email }); }}>
            <label>{t("friendEmail")}<input name="email" type="email" required maxLength={254} placeholder="friend@example.com" disabled={busy} /></label>
            <button type="submit" disabled={busy}>{t("createInvite")}</button>
          </form>
          {inviteLink && <label>{t("inviteLink")}<input readOnly value={inviteLink} onFocus={event => event.target.select()} /></label>}
          <ul>{page.invitations.map(invitation => <li key={invitation.id}>
            <span>{invitation.email} · {t(invitation.accepted ? "inviteAccepted" : "invitePending")}</span>
            <button type="button" disabled={busy} onClick={() => action(`/invitations/${invitation.id}/revoke`, {})}>{t("removeInvite")}</button>
          </li>)}</ul>
        </>}
      </section>}
    </>}
  </main>;
}
