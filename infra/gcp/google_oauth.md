# Google OAuth for CopyMe2 Memoir

This guide configures Google sign-in through Supabase. It does not configure
Vertex AI, Maps, or the local `llm-provider`.

## Values for this project

- Google Cloud project: `copyme2ai-memoir`
- Supabase project ref: `vpzhimeqmuzyzfozcjnq`
- Supabase dashboard: <https://supabase.com/dashboard/project/vpzhimeqmuzyzfozcjnq/auth/providers?provider=Google>
- Google OAuth callback URL:

  ```text
  https://vpzhimeqmuzyzfozcjnq.supabase.co/auth/v1/callback
  ```

The callback URL above is entered in Google Cloud. It is not the URL where the
browser returns after sign-in.

## 1. Create the Google Web OAuth client

1. Open [Google Cloud Credentials](https://console.cloud.google.com/apis/credentials?project=copyme2ai-memoir)
   and select project `copyme2ai-memoir`.

2. Configure the OAuth consent screen. In the current console this is under
   **Google Auth Platform → Branding**; older console layouts show
   **APIs & Services → OAuth consent screen**.

   Use values such as:

   - App name: `CopyMe2 Memoir`
   - User support email: the Google account that owns the project
   - Audience: **External** unless this is restricted to a Google Workspace
     organization
   - Developer contact email: the project owner’s email

   Save the branding settings. If the app remains in testing, add every Google
   account that will test it under **Audience → Test users**.

3. Open **Google Auth Platform → Clients** (or **APIs & Services →
   Credentials**) and click **Create client**.

4. Choose **Web application**. Give it a name such as
   `copyme2ai-memoir-web`.

5. Add the browser origins under **Authorized JavaScript origins**. Add only
   origins that the application actually uses:

   ```text
   http://localhost:3010
   http://127.0.0.1:3010
   ```

   If the production application uses these hosts, add them as separate
   origins:

   ```text
   https://copyme2.ai
   https://app.copyme2.ai
   ```

   An origin contains only the scheme, hostname, and optional port. Do not add
   `/memoir/start` or a wildcard to this field.

6. Under **Authorized redirect URIs**, add this exact URI:

   ```text
   https://vpzhimeqmuzyzfozcjnq.supabase.co/auth/v1/callback
   ```

   Do not replace it with the local web URL. Supabase receives the Google
   callback and then redirects the browser back to the application.

7. Click **Create**. Copy the generated **Client ID** and **Client secret**.
   Store the secret in a password manager until it is entered into Supabase.
   Never commit it, put it in `apps/web/public`, or expose it in browser
   JavaScript.

Google’s reference flow is described in [Get your Google API client ID](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid)
and [Using OAuth 2.0 for Web Server Applications](https://developers.google.com/identity/protocols/oauth2/web-server).

## 2. Configure the Google provider in Supabase

1. Open the [Supabase Google provider settings](https://supabase.com/dashboard/project/vpzhimeqmuzyzfozcjnq/auth/providers?provider=Google).

2. Turn on **Enable Sign in with Google**.

3. Paste the Google Web application **Client ID** and **Client secret**.

4. Confirm that Supabase displays this callback URL:

   ```text
   https://vpzhimeqmuzyzfozcjnq.supabase.co/auth/v1/callback
   ```

5. Click **Save**.

Supabase’s provider-specific instructions are in [Login with Google](https://supabase.com/docs/guides/auth/social-login/auth-google).

## 3. Configure where Supabase may return the browser

In Supabase, open **Authentication → URL Configuration**.

Set the **Site URL** to the URL used for the current environment. For local
development, use one host consistently, for example:

```text
http://127.0.0.1:3010
```

Add the redirect URLs that the web app may use. The current app redirects to
`/memoir/start`, so local development can include:

```text
http://127.0.0.1:3010/memoir/start
http://localhost:3010/memoir/start
```

Add the production equivalents only when those domains are deployed:

```text
https://copyme2.ai/memoir/start
https://app.copyme2.ai/memoir/start
```

These are Supabase application redirect URLs. They are different from the
Google authorized redirect URI in the previous section. See Supabase’s
[redirect URL documentation](https://supabase.com/docs/guides/auth/redirect-urls).

## 4. Match the current app’s authentication flow

The current web app first uses an anonymous Supabase session and later calls
`linkIdentity` to attach a social identity. For that flow, enable these in
Supabase Auth settings:

- **Allow anonymous sign-ins**
- **Allow manual linking**

If the application is changed to start directly with Google sign-in, these two
settings are not required. The relevant Supabase references are [anonymous
sign-ins](https://supabase.com/docs/guides/auth/auth-anonymous) and [manual
identity linking](https://supabase.com/docs/guides/auth/auth-identity-linking#manual-linking-beta).

## 5. What belongs in `.env`

For Supabase Google sign-in, the browser only needs the normal Supabase URL and
publishable key. Do not add the Google client secret to the web app’s env file.
Supabase stores the Google client secret in its provider configuration.

The current project uses the external `MEMORY_SPARK_LLM_*` provider. Therefore
these Vertex/service-account variables are not needed for this OAuth setup:

```text
GOOGLE_APPLICATION_CREDENTIALS
GCP_KEY_FILE
GOOGLE_CLOUD_PROJECT
GOOGLE_CLOUD_LOCATION
GOOGLE_GENAI_USE_VERTEXAI
```

A Maps API key is a separate concern. If Maps is added later, use a browser
API key restricted by HTTP referrers for browser code; it is unrelated to the
Google OAuth client secret.

## 6. Verify the setup

1. Start the local web app at `http://127.0.0.1:3010`.
2. Start the Google sign-in/link flow.
3. Complete Google consent using an account listed as a test user if the OAuth
   app is still in testing.
4. Confirm that the browser returns to `/memoir/start` and that the Supabase session
   remains authenticated after a refresh.

Common failures:

- `redirect_uri_mismatch`: the Google redirect URI is not an exact match. Check
  the Supabase callback URI, including scheme and path.
- `provider is disabled`: the Google provider was not enabled and saved in
  Supabase.
- `invalid client`: the client ID and secret are from different Google OAuth
  clients or different projects.
- `redirect not allowed`: the final `/memoir/start` URL is missing from Supabase
  **Authentication → URL Configuration**.
- `access blocked`: the Google account is not listed as a test user while the
  consent screen is in testing mode.
