// Product route catalog. The current client is a small vanilla SPA, so these
// routes are intentionally data-first and can move into framework page files
// later without changing the public URL contract.
export const PRODUCT_ROUTES = Object.freeze({
  platform: "/",
  memoir: "/memoir",
  voice: "/voice",
});

export const MEMOIR_ROUTES = Object.freeze({
  home: "/memoir",
  start: "/memoir/start",
  myStory: "/memoir/my-story",
  interview: "/memoir/interview",
  memories: "/memoir/memories",
  diary: "/memoir/diary",
  photos: "/memoir/photos",
  people: "/memoir/people",
  timeline: "/memoir/timeline",
  chapters: "/memoir/chapters",
  preview: "/memoir/preview",
  package: "/memoir/package",
  checkout: "/memoir/checkout",
  book: "/memoir/book",
  print: "/memoir/print",
  settings: "/memoir/settings",
  family: "/memoir/family",
});

export const MEMOIR_ROUTE_DETAILS = Object.freeze([
  [MEMOIR_ROUTES.home, "Memoir marketing and entry page"],
  [MEMOIR_ROUTES.start, "Start the free memory journey"],
  [MEMOIR_ROUTES.myStory, "Storyteller home and progress"],
  [`${MEMOIR_ROUTES.interview}/:sessionId`, "Current Memory Spark interview"],
  [MEMOIR_ROUTES.memories, "Saved memories"],
  [`${MEMOIR_ROUTES.memories}/:id`, "Memory review and edit"],
  [MEMOIR_ROUTES.diary, "Ongoing diary"],
  [MEMOIR_ROUTES.photos, "Photo and document library"],
  [MEMOIR_ROUTES.people, "Family tree and people"],
  [MEMOIR_ROUTES.timeline, "Life timeline"],
  [MEMOIR_ROUTES.chapters, "Chapter workspace"],
  [`${MEMOIR_ROUTES.chapters}/:id`, "Chapter editor"],
  [MEMOIR_ROUTES.preview, "Free mini-memoir preview"],
  [MEMOIR_ROUTES.package, "Paid package explanation"],
  [MEMOIR_ROUTES.checkout, "Checkout"],
  [MEMOIR_ROUTES.book, "Finished book and editions"],
  [MEMOIR_ROUTES.print, "Print ordering"],
  [MEMOIR_ROUTES.settings, "Privacy, access, export, and deletion"],
  [MEMOIR_ROUTES.family, "Family collaboration"],
  [`${MEMOIR_ROUTES.family}/people`, "Family people"],
  [`${MEMOIR_ROUTES.family}/review`, "Family review"],
]);
