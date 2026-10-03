import assert from "node:assert/strict";
import test from "node:test";

import { currentUiLocale, translate } from "../../apps/web/client/i18n.js";

test("Chinese document locale keeps client fallback copy localized", () => {
  const previousDocument = globalThis.document;
  const previousIntl = globalThis.__copyme2Intl;
  globalThis.document = { documentElement: { lang: "zh-CN" } };
  delete globalThis.__copyme2Intl;

  try {
    assert.equal(currentUiLocale(), "zh-CN");
    assert.equal(translate("Memoir.trace.title"), "思考步骤");
    assert.equal(translate("Memoir.story.listenButton"), "朗读 · AI 语音");
    assert.equal(translate("AuthReminder.title"), "登录以保留聊天记录");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
    if (previousIntl === undefined) delete globalThis.__copyme2Intl;
    else globalThis.__copyme2Intl = previousIntl;
  }
});
