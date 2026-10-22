// app.js — vanilla ES-module SPA for the video streaming app.
//
// Startup ALWAYS fetches config.json (never branch on hostname). In AWS the
// BucketDeployment writes { apiBaseUrl: "/api", playbackMode: "cookie", region };
// locally the developer runs `cp config.local.json config.json`, giving
// { apiBaseUrl: "http://127.0.0.1:8000", playbackMode: "signed-url", region }.

import { play, destroyPlayer } from "./player.js";

const POLL_INTERVAL_MS = 5000;

const els = {
  uploadForm: document.getElementById("upload-form"),
  titleInput: document.getElementById("title-input"),
  fileInput: document.getElementById("file-input"),
  uploadButton: document.getElementById("upload-button"),
  uploadStatus: document.getElementById("upload-status"),
  gallery: document.getElementById("gallery"),
  galleryEmpty: document.getElementById("gallery-empty"),
  galleryLoading: document.getElementById("gallery-loading"),
  galleryError: document.getElementById("gallery-error"),
  galleryNomatch: document.getElementById("gallery-nomatch"),
  playerSection: document.getElementById("player-section"),
  playerTitle: document.getElementById("player-title"),
  playerStatus: document.getElementById("player-status"),
  player: document.getElementById("player"),
  playerClose: document.getElementById("player-close"),
  dropzone: document.getElementById("dropzone"),
  dropzoneFilename: document.getElementById("dropzone-filename"),
  searchInput: document.getElementById("search-input"),
  uploadModal: document.getElementById("upload-modal"),
};

let config = null;
let firstLoad = true;
let allVideos = [];
let searchQuery = "";

function api(path) {
  // apiBaseUrl is "/api" (same-origin, prod) or "http://127.0.0.1:8000" (local).
  return `${config.apiBaseUrl}${path}`;
}

async function loadConfig() {
  const resp = await fetch("config.json", { cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`failed to load config.json (${resp.status})`);
  }
  return resp.json();
}

async function listVideos() {
  const resp = await fetch(api("/videos"));
  if (!resp.ok) {
    throw new Error(`list failed (${resp.status})`);
  }
  const data = await resp.json();
  return data.videos || [];
}

async function uploadVideo(file, title) {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title);
  const resp = await fetch(api("/videos"), { method: "POST", body: form });
  if (!resp.ok) {
    throw new Error(`upload failed (${resp.status})`);
  }
  return resp.json();
}

async function deleteVideo(videoId) {
  const resp = await fetch(api(`/videos/${videoId}`), { method: "DELETE" });
  if (!resp.ok) {
    throw new Error(`delete failed (${resp.status})`);
  }
  return resp.json();
}

async function fetchPlayUrl(videoId) {
  const resp = await fetch(api(`/videos/${videoId}/play-url`));
  if (resp.status === 409) {
    const body = await resp.json().catch(() => ({}));
    const status = (body.detail && body.detail.status) || "not ready";
    const err = new Error(`not ready (${status})`);
    err.notReady = status;
    throw err;
  }
  if (!resp.ok) {
    throw new Error(`play-url failed (${resp.status})`);
  }
  return resp.json();
}

function badge(status) {
  const span = document.createElement("span");
  const normalized = String(status || "").toLowerCase();
  span.className = `badge ${normalized}`;
  span.textContent = status || "unknown";
  return span;
}

function videoLabel(video) {
  return video.title || video.original_filename || video.video_id;
}

// Relative time from whichever timestamp field the API provides (optional).
function relativeTime(video) {
  const raw =
    video.created_at ||
    video.createdAt ||
    video.uploaded_at ||
    video.uploadedAt ||
    video.updated_at ||
    video.updatedAt;
  if (!raw) return "";
  const then = new Date(raw).getTime();
  if (Number.isNaN(then)) return "";
  const diffSec = Math.round((Date.now() - then) / 1000);
  if (diffSec < 45) return "just now";
  const units = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [name, secs] of units) {
    const n = Math.floor(diffSec / secs);
    if (n >= 1) return `${n} ${name}${n > 1 ? "s" : ""} ago`;
  }
  return "just now";
}

function thumbPlaceholder() {
  const span = document.createElement("span");
  span.className = "thumb-placeholder";
  span.setAttribute("aria-hidden", "true");
  span.innerHTML =
    '<svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="4.5" width="19" height="15" rx="2.5"/><path d="M10 9.5l4.5 2.5L10 14.5z" fill="currentColor" stroke="none"/></svg>';
  return span;
}

function createCard(video) {
  const li = document.createElement("li");
  li.className = "video-card";

  const thumb = document.createElement("div");
  thumb.className = "video-thumb";
  if (video.thumbnail_url) {
    const img = document.createElement("img");
    img.src = video.thumbnail_url;
    img.alt = "";
    thumb.append(img);
  } else {
    thumb.append(thumbPlaceholder());
  }

  const statusBadge = badge(video.status);
  statusBadge.classList.add("thumb-badge");
  thumb.append(statusBadge);

  const isReady = video.status === "Ready";
  if (isReady) {
    const thumbPlay = document.createElement("button");
    thumbPlay.type = "button";
    thumbPlay.className = "thumb-play";
    thumbPlay.setAttribute("aria-label", `Play ${videoLabel(video)}`);
    thumbPlay.innerHTML =
      '<span><svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg></span>';
    thumbPlay.addEventListener("click", () => onPlay(video));
    thumb.append(thumbPlay);
  }

  const body = document.createElement("div");
  body.className = "video-body";

  const title = document.createElement("span");
  title.className = "title";
  title.textContent = videoLabel(video);
  body.append(title);

  const when = relativeTime(video);
  if (when) {
    const sub = document.createElement("span");
    sub.className = "video-sub";
    sub.textContent = when;
    body.append(sub);
  }

  const actions = document.createElement("div");
  actions.className = "video-actions";

  const playBtn = document.createElement("button");
  playBtn.type = "button";
  playBtn.className = "btn btn-primary btn-sm";
  playBtn.textContent = "Play";
  playBtn.disabled = !isReady;
  playBtn.addEventListener("click", () => onPlay(video));

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "btn btn-secondary btn-sm secondary";
  deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", () => onDelete(video));

  actions.append(playBtn, deleteBtn);
  body.append(actions);

  li.append(thumb, body);
  return li;
}

function filterVideos() {
  const q = searchQuery.trim().toLowerCase();
  if (!q) return allVideos;
  return allVideos.filter((v) => videoLabel(v).toLowerCase().includes(q));
}

// Render the library from the cached video list + current search query.
function renderLibrary() {
  els.gallery.replaceChildren();
  if (els.galleryLoading) els.galleryLoading.hidden = true;
  if (els.galleryError) els.galleryError.hidden = true;

  if (allVideos.length === 0) {
    els.galleryEmpty.hidden = false;
    if (els.galleryNomatch) els.galleryNomatch.hidden = true;
    return;
  }

  els.galleryEmpty.hidden = true;
  const visible = filterVideos();
  if (visible.length === 0) {
    if (els.galleryNomatch) els.galleryNomatch.hidden = false;
    return;
  }
  if (els.galleryNomatch) els.galleryNomatch.hidden = true;

  for (const video of visible) {
    els.gallery.append(createCard(video));
  }
}

async function refreshGallery() {
  if (firstLoad && els.galleryLoading) {
    els.galleryLoading.hidden = false;
    els.galleryEmpty.hidden = true;
    if (els.galleryError) els.galleryError.hidden = true;
    if (els.galleryNomatch) els.galleryNomatch.hidden = true;
  }
  try {
    allVideos = await listVideos();
    renderLibrary();
  } catch (err) {
    if (els.galleryLoading) els.galleryLoading.hidden = true;
    els.galleryEmpty.hidden = true;
    if (els.galleryNomatch) els.galleryNomatch.hidden = true;
    if (els.galleryError) els.galleryError.hidden = false;
    console.error(err);
  } finally {
    firstLoad = false;
  }
}

async function onPlay(video) {
  els.playerSection.hidden = false;
  els.playerTitle.textContent = `Now playing: ${videoLabel(video)}`;
  els.playerStatus.textContent = "Loading…";
  try {
    const { play_url: playUrl } = await fetchPlayUrl(video.video_id);
    els.playerStatus.textContent = "";
    play(els.player, playUrl, {
      onRefresh: async () => {
        const fresh = await fetchPlayUrl(video.video_id);
        return fresh.play_url;
      },
    });
  } catch (err) {
    if (err.notReady) {
      els.playerStatus.textContent = `Not ready yet (${err.notReady}).`;
    } else {
      els.playerStatus.textContent = "Could not start playback.";
      console.error(err);
    }
  }
}

function closePlayer() {
  destroyPlayer(els.player);
  els.player.pause();
  els.player.removeAttribute("src");
  els.player.load();
  els.playerStatus.textContent = "";
  els.playerSection.hidden = true;
}

async function onDelete(video) {
  try {
    await deleteVideo(video.video_id);
    await refreshGallery();
  } catch (err) {
    console.error(err);
  }
}

/* ---------- Upload modal ---------- */
function openUploadModal() {
  if (!els.uploadModal) return;
  els.uploadModal.hidden = false;
  els.fileInput.focus({ preventScroll: true });
}

function closeUploadModal() {
  if (!els.uploadModal) return;
  els.uploadModal.hidden = true;
}

/* ---------- Dropzone ---------- */
function updateDropzoneFilename() {
  if (!els.dropzoneFilename) return;
  const file = els.fileInput.files[0];
  if (file) {
    els.dropzoneFilename.textContent = file.name;
    els.dropzoneFilename.hidden = false;
  } else {
    els.dropzoneFilename.textContent = "";
    els.dropzoneFilename.hidden = true;
  }
}

function wireDropzone() {
  els.fileInput.addEventListener("change", updateDropzoneFilename);

  const zone = els.dropzone;
  if (!zone) return;

  ["dragenter", "dragover"].forEach((name) =>
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.add("is-dragover");
    }),
  );

  ["dragleave", "dragend"].forEach((name) =>
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.remove("is-dragover");
    }),
  );

  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("is-dragover");
    const dropped = event.dataTransfer && event.dataTransfer.files;
    if (dropped && dropped.length > 0) {
      // Route the dropped file through the existing #file-input so all upload
      // logic (els.fileInput.files[0]) keeps working unchanged.
      els.fileInput.files = dropped;
      updateDropzoneFilename();
    }
  });
}

async function onUploadSubmit(event) {
  event.preventDefault();
  const file = els.fileInput.files[0];
  if (!file) {
    return;
  }
  els.uploadButton.disabled = true;
  els.uploadStatus.textContent = "Uploading…";
  try {
    const result = await uploadVideo(file, els.titleInput.value);
    els.uploadStatus.textContent = `Uploaded. Status: ${result.status}.`;
    els.uploadForm.reset();
    updateDropzoneFilename();
    await refreshGallery();
    // Close the modal on success so the new video is visible in the library.
    els.uploadStatus.textContent = "";
    closeUploadModal();
  } catch (err) {
    els.uploadStatus.textContent = "Upload failed.";
    console.error(err);
  } finally {
    els.uploadButton.disabled = false;
  }
}

function wireModals() {
  // Any [data-upload-open] trigger (top bar, hero, empty-state CTA).
  document.querySelectorAll("[data-upload-open]").forEach((btn) =>
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      openUploadModal();
    }),
  );

  // Upload modal close (backdrop + close button both carry data-upload-close).
  if (els.uploadModal) {
    els.uploadModal.addEventListener("click", (event) => {
      if (
        event.target instanceof Element &&
        event.target.closest("[data-upload-close]")
      ) {
        closeUploadModal();
      }
    });
  }

  // Player modal close (backdrop + close button).
  if (els.playerClose) {
    els.playerClose.addEventListener("click", closePlayer);
  }
  els.playerSection.addEventListener("click", (event) => {
    if (
      event.target instanceof Element &&
      event.target.hasAttribute("data-player-close")
    ) {
      closePlayer();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!els.playerSection.hidden) {
      closePlayer();
    } else if (els.uploadModal && !els.uploadModal.hidden) {
      closeUploadModal();
    }
  });
}

function wireSearch() {
  if (!els.searchInput) return;
  els.searchInput.addEventListener("input", () => {
    searchQuery = els.searchInput.value;
    renderLibrary();
  });
}

async function init() {
  config = await loadConfig();
  els.uploadForm.addEventListener("submit", onUploadSubmit);
  wireDropzone();
  wireModals();
  wireSearch();

  await refreshGallery();
  setInterval(refreshGallery, POLL_INTERVAL_MS);
}

init().catch((err) => {
  console.error(err);
  els.uploadStatus.textContent = "Failed to initialize the app.";
});
