import { $, escapeHtml } from "./dom.mjs";
import { currentUiLocale, translateWith } from "../i18n.js";

export const FALLBACK_STORY_PLANS = [
  { plan_key: "electronic_memoir_v1", name: "Electronic memoir", price_minor: 4900, description: "A beautifully shaped electronic version of your memoir.", features: ["Electronic memoir", "Source-linked story chapters", "Private digital delivery"], electronic_only: true, additional_book_price_minor: 0, minimum_books: 0, default_books: 0 },
  { plan_key: "printed_memoir_v1", name: "Printed memoir", price_minor: 7900, description: "Two printed books, with extra copies available for A$10 each.", features: ["Electronic memoir", "2 printed books", "Add extra books for A$10 each"], electronic_only: false, additional_book_price_minor: 1000, minimum_books: 2, default_books: 2 },
  { plan_key: "family_memoir_v1", name: "Family legacy memoir", price_minor: 12900, description: "Two printed books plus a richer family record.", features: ["Electronic memoir", "2 printed books", "Family tree", "Life timeline", "More detailed story context"], electronic_only: false, additional_book_price_minor: 1000, minimum_books: 2, default_books: 2 },
];

export function createStoryCheckout({
  authReminder, render, state, storyApi, toast
}) {
  function formatAudMinor(amountMinor) {
    return new Intl.NumberFormat(currentUiLocale(), { style: "currency", currency: "AUD", currencyDisplay: "code", maximumFractionDigits: 0 }).format(Number(amountMinor || 0) / 100);
  }

  function storyPlanTotal(plan, bookCount) {
    if (plan.electronic_only) return plan.price_minor;
    return plan.price_minor + Math.max(0, Number(bookCount || plan.default_books || 2) - 2) * (plan.additional_book_price_minor || 1000);
  }

  function storyPlanCopy(plan) {
    const copy = globalThis.__copyme2Intl?.messages?.Memoir?.storyFlow?.plans?.[plan.plan_key];
    if (!copy) return { name: plan.name, description: plan.description, features: plan.features || [] };
    return { ...copy, features: Object.values(copy.features || {}) };
  }

  function storyCheckoutForm() {
    const plans = state.storyPlans.length ? state.storyPlans : FALLBACK_STORY_PLANS;
    const selectedPlan = plans.find((plan) => plan.plan_key === state.selectedStoryPlan) || plans[0];
    const selectedKey = selectedPlan.plan_key;
    const bookCount = Math.max(2, Number(state.storyBookCount || selectedPlan.default_books || 2));
    const printed = !selectedPlan.electronic_only;
    const total = storyPlanTotal(selectedPlan, printed ? bookCount : 0);
    const t = (key, values = {}) => escapeHtml(translateWith(`Memoir.storyFlow.${key}`, values));
    const checkoutMessage = state.checkout?.message ? `<p class="fine-print story-payment-note">${escapeHtml(state.checkout.message)}</p>` : "";
    return `
      <form id="story-checkout-form" class="story-checkout-form">
        <div class="story-plan-grid" role="radiogroup" aria-label="${t("packagesLabel")}">
          ${plans.map((plan) => { const copy = storyPlanCopy(plan); return `
            <label class="story-plan-card ${plan.plan_key === selectedKey ? "selected" : ""}">
              <input type="radio" name="plan_key" value="${escapeHtml(plan.plan_key)}" ${plan.plan_key === selectedKey ? "checked" : ""} />
              <span class="story-plan-card-top"><span class="eyebrow">${escapeHtml(copy.name)}</span><strong>${t("fromPrice", { price: formatAudMinor(plan.price_minor) })}</strong></span>
              <span class="story-plan-description">${escapeHtml(copy.description)}</span>
              <span class="story-plan-features">${copy.features.map((feature) => `<span>✓ ${escapeHtml(feature)}</span>`).join("")}</span>
            </label>`; }).join("")}
        </div>
        <div class="story-book-options ${printed ? "" : "is-disabled"}">
          <label for="story-book-count"><span>${t("printedBooks")}</span><select id="story-book-count" name="book_count" ${printed ? "" : "disabled"}>${Array.from({ length: 19 }, (_, index) => index + 2).map((count) => `<option value="${count}" ${count === bookCount ? "selected" : ""}>${t("bookCount", { count })}${count > 2 ? t("extraBooks", { price: formatAudMinor((count - 2) * 1000) }) : ""}</option>`).join("")}</select></label>
          <div class="story-checkout-total"><span>${t("totalToday")}</span><strong data-story-total>${formatAudMinor(total)}</strong></div>
        </div>
        <button type="submit" class="button button-primary" ${state.loading ? "disabled" : ""}>${t("continueCheckout")} <span>↗</span></button>
        <p class="fine-print">${t("pricesNote")}</p>
        ${checkoutMessage}
      </form>`;
  }

  async function refreshStoryState(shouldRender = true) {
    state.story = await storyApi("/v1/story/state");
    if (!state.storyPlans.length) {
      state.storyPlans = (await storyApi("/v1/story/plans")).items || [];
    }
    if (shouldRender && state.story) render();
    return state.story;
  }

  async function requestStoryCheckout() {
    if (state.loading) return;
    const selectedPlan = $("input[name='plan_key']:checked")?.value || state.selectedStoryPlan || "electronic_memoir_v1";
    const plan = (state.storyPlans.length ? state.storyPlans : FALLBACK_STORY_PLANS).find((item) => item.plan_key === selectedPlan);
    const bookCount = plan?.electronic_only ? 0 : (Number($("#story-book-count")?.value) || state.storyBookCount || 2);
    state.selectedStoryPlan = selectedPlan;
    state.storyBookCount = bookCount || 2;
    try {
      sessionStorage.setItem("memoir-package-choice", JSON.stringify({ plan: selectedPlan, books: state.storyBookCount }));
    } catch { /* The current selection remains usable without browser storage. */ }
    if (state.supabase?.user?.is_anonymous) {
      authReminder.open();
      return;
    }
    state.loading = true;
    try {
      state.checkout = await storyApi("/v1/story/checkout", {
        method: "POST",
        body: JSON.stringify({ plan_key: selectedPlan, book_count: bookCount }),
      });
      if (state.checkout.checkout_url) {
        window.location.assign(state.checkout.checkout_url);
        return;
      }
    } catch (error) {
      toast(error.message);
    } finally {
      state.loading = false;
      render();
    }
  }

  return {
    refreshStoryState, requestStoryCheckout, storyCheckoutForm
  };
}
