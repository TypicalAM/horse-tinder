"use strict";

const $ = (sel) => document.querySelector(sel);

const SWIPE_THRESHOLD = 110;

const state = {
  queue: [],          // horses waiting to be swiped, queue[0] is on top
  swiped: new Set(),  // ids swiped this session, filtered from refills
  loading: false,
  exhausted: false,
  chatHorse: null,
};

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  if (!res.ok) throw new Error(`${options.method || "GET"} ${path}: ${res.status}`);
  return res.json();
}

/* ---------- Deck ---------- */

async function refill() {
  if (state.loading || state.queue.length >= 3) return;
  state.loading = true;
  try {
    const { horses } = await api("/api/horses?limit=6");
    const known = new Set(state.queue.map((h) => h.id));
    const fresh = horses.filter((h) => !known.has(h.id) && !state.swiped.has(h.id));
    state.queue.push(...fresh);
    // Fewer results than asked for and nothing new means the server has run out.
    state.exhausted = horses.length < 6 && fresh.length === 0;
    for (const h of fresh) new Image().src = h.photo;
  } finally {
    state.loading = false;
  }
  renderDeck();
}

function buildCard(horse) {
  const node = $("#card-template").content.firstElementChild.cloneNode(true);
  node.dataset.id = horse.id;
  const img = node.querySelector(".card-photo");
  img.src = horse.photo;
  img.alt = `Photo of ${horse.name}`;
  img.style.objectPosition = horse.photo_position;
  node.querySelector(".card-name").textContent = horse.name;
  node.querySelector(".card-age").textContent = horse.age;
  node.querySelector(".card-meta").textContent = `${horse.breed} · ${horse.location}`;
  node.querySelector(".card-bio").textContent = horse.bio;
  const tags = node.querySelector(".card-tags");
  for (const interest of horse.interests) {
    const li = document.createElement("li");
    li.textContent = interest;
    tags.append(li);
  }
  const credit = node.querySelector(".card-credit");
  credit.href = horse.photo_source;
  credit.textContent = `Photo: ${horse.photo_artist} · ${horse.photo_license} · Wikimedia Commons`;
  credit.addEventListener("pointerdown", (e) => e.stopPropagation());
  return node;
}

function renderDeck() {
  const deck = $("#deck");
  const visible = state.queue.slice(0, 2);
  const wanted = visible.map((h) => String(h.id));

  for (const card of [...deck.children]) {
    if (!wanted.includes(card.dataset.id) && !card.classList.contains("is-leaving")) card.remove();
  }
  // The top horse is the last child (painted on top), so newcomers go underneath.
  for (const horse of visible) {
    if (!deck.querySelector(`.card[data-id="${horse.id}"]:not(.is-leaving)`)) {
      deck.prepend(buildCard(horse));
    }
  }
  const top = topCard();
  for (const card of deck.querySelectorAll(".card:not(.is-leaving)")) {
    card.classList.toggle("is-under", card !== top);
  }
  if (top && !top.dataset.bound) bindDrag(top);

  const empty = state.queue.length === 0 && state.exhausted;
  $("#empty").hidden = !empty;
  $("#deck").hidden = empty;
  $("#actions").hidden = empty;
  $(".hint").hidden = empty;
}

function topCard() {
  const cards = $("#deck").querySelectorAll(".card:not(.is-leaving)");
  return cards[cards.length - 1] || null;
}

function setStamps(card, dx) {
  const strength = Math.min(Math.abs(dx) / SWIPE_THRESHOLD, 1);
  card.querySelector(".stamp-like").style.opacity = dx > 0 ? strength : 0;
  card.querySelector(".stamp-nope").style.opacity = dx < 0 ? strength : 0;
}

function bindDrag(card) {
  card.dataset.bound = "1";
  let startX = 0;
  let startY = 0;
  let dx = 0;
  let dy = 0;
  let dragging = false;

  card.addEventListener("pointerdown", (e) => {
    dragging = true;
    startX = e.clientX;
    startY = e.clientY;
    dx = dy = 0;
    card.setPointerCapture(e.pointerId);
    card.classList.add("is-dragging");
  });

  card.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    dx = e.clientX - startX;
    dy = e.clientY - startY;
    card.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx / 14}deg)`;
    setStamps(card, dx);
  });

  const end = () => {
    if (!dragging) return;
    dragging = false;
    card.classList.remove("is-dragging");
    if (Math.abs(dx) > SWIPE_THRESHOLD) {
      swipe(dx > 0, dy);
    } else {
      card.style.transform = "";
      setStamps(card, 0);
    }
  };
  card.addEventListener("pointerup", end);
  card.addEventListener("pointercancel", end);
}

async function swipe(liked, dy = 0) {
  const card = topCard();
  const horse = state.queue[0];
  if (!card || !horse) return;

  state.queue.shift();
  state.swiped.add(horse.id);

  card.classList.add("is-leaving");
  card.classList.remove("is-dragging");
  setStamps(card, liked ? SWIPE_THRESHOLD : -SWIPE_THRESHOLD);
  const x = (liked ? 1 : -1) * (window.innerWidth + 200);
  card.style.transform = `translate(${x}px, ${dy}px) rotate(${liked ? 30 : -30}deg)`;
  card.style.opacity = "0";
  card.addEventListener("transitionend", () => card.remove(), { once: true });
  setTimeout(() => card.remove(), 500);

  renderDeck();
  refill();

  try {
    const result = await api("/api/swipes", {
      method: "POST",
      body: JSON.stringify({ horse_id: horse.id, liked }),
    });
    if (result.matched) {
      showMatch(result.horse);
      refreshMatchCount();
    }
  } catch (err) {
    console.error(err);
  }
  refill();
}

/* ---------- Match modal ---------- */

function showMatch(horse) {
  $("#modal-photo").src = horse.photo;
  $("#modal-photo").alt = horse.name;
  $("#modal-photo").style.objectPosition = horse.photo_position;
  $("#modal-text").textContent = `${horse.name} liked you back. Say something before they wander off to graze.`;
  $("#match-modal").hidden = false;
  $("#modal-chat").onclick = () => {
    $("#match-modal").hidden = true;
    openChat(horse);
  };
}

$("#modal-close").addEventListener("click", () => ($("#match-modal").hidden = true));

/* ---------- Views ---------- */

function showView(name) {
  for (const view of document.querySelectorAll(".view")) view.hidden = view.id !== `view-${name}`;
  const tabName = name === "chat" ? "matches" : name;
  for (const tab of document.querySelectorAll(".tab")) {
    const active = tab.dataset.view === tabName;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", active);
  }
}

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => {
    if (tab.dataset.view === "matches") loadMatches();
    showView(tab.dataset.view);
  });
}

async function refreshMatchCount() {
  const { matches } = await api("/api/matches");
  const badge = $("#match-count");
  badge.textContent = matches.length;
  badge.hidden = matches.length === 0;
  return matches;
}

async function loadMatches() {
  const matches = await refreshMatchCount();
  const list = $("#match-list");
  list.replaceChildren();
  $("#matches-empty").hidden = matches.length > 0;
  for (const horse of matches) {
    const btn = document.createElement("button");
    btn.className = "match";
    const img = document.createElement("img");
    img.src = horse.photo;
    img.alt = horse.name;
    img.style.objectPosition = horse.photo_position;
    const body = document.createElement("div");
    body.className = "match-body";
    const name = document.createElement("div");
    name.className = "match-name";
    name.textContent = horse.name;
    const last = document.createElement("div");
    last.className = "match-last";
    last.textContent = horse.last_message || "Say hi!";
    body.append(name, last);
    btn.append(img, body);
    btn.addEventListener("click", () => openChat(horse));
    list.append(btn);
  }
}

/* ---------- Chat ---------- */

function renderMessages(messages) {
  const list = $("#messages");
  list.replaceChildren();
  for (const m of messages) {
    const li = document.createElement("li");
    li.className = `msg ${m.from_horse ? "horse" : "me"}`;
    li.textContent = m.body;
    list.append(li);
  }
  list.scrollTop = list.scrollHeight;
}

async function openChat(horse) {
  state.chatHorse = horse;
  $("#chat-avatar").src = horse.photo;
  $("#chat-avatar").style.objectPosition = horse.photo_position;
  $("#chat-name").textContent = horse.name;
  $("#chat-sub").textContent = `${horse.breed} · ${horse.location}`;
  showView("chat");
  const { messages } = await api(`/api/matches/${horse.id}/messages`);
  renderMessages(messages);
  $("#composer-input").focus();
}

$("#chat-back").addEventListener("click", () => {
  loadMatches();
  showView("matches");
});

$("#composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#composer-input");
  const body = input.value.trim();
  if (!body || !state.chatHorse) return;
  input.value = "";
  const { messages } = await api(`/api/matches/${state.chatHorse.id}/messages`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
  renderMessages(messages);
});

/* ---------- Controls ---------- */

$("#btn-like").addEventListener("click", () => swipe(true));
$("#btn-nope").addEventListener("click", () => swipe(false));

document.addEventListener("keydown", (e) => {
  if ($("#view-discover").hidden || !$("#match-modal").hidden) return;
  if (e.key === "ArrowRight") swipe(true);
  if (e.key === "ArrowLeft") swipe(false);
});

$("#reset").addEventListener("click", async () => {
  await api("/api/reset", { method: "POST" });
  state.queue = [];
  state.swiped.clear();
  state.exhausted = false;
  refreshMatchCount();
  refill();
});

refill();
refreshMatchCount();
