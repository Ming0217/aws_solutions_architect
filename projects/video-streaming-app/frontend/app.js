// app.js — vanilla ES-module SPA for the video streaming app.
//
// Startup ALWAYS fetches config.json (never branch on hostname). In AWS the
// BucketDeployment writes { apiBaseUrl: "/api", playbackMode: "cookie", region };
// locally the developer runs `cp config.local.json config.json`, giving
// { apiBaseUrl: "http://127.0.0.1:8000", playbackMode: "signed-url", region }.

import { play } from "./player.js";

const POLL_INTERVAL_MS = 5000;

const els = {
  uploadForm: document.getElementById("upload-form"),
  titleInput: document.getElementById("title-input"),
  fileInput: document.getElementById("file-input"),
  uploadButton: document.getElementById("upload-button"),
  uploadStatus: document.getElementById("upload-status"),
  gallery: document.getElementById("gallery"),
  galleryEmpty: document.getElementById("gallery-empty"),
  playerSection: document.getElementById("player-section"),
  playerTitle: document.getElementById("player-title"),
  playerStatus: document.getElementById("player-status"),
  player: document.getElementById("player"),
};

let config = null;

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

function renderGallery(videos) {
  els.gallery.replaceChildren();
  els.galleryEmpty.hidden = videos.length > 0;

  for (const video of videos) {
    const li = document.createElement("li");

    const title = document.createElement("span");
    title.className = "title";
    title.textContent = video.title || video.original_filename || video.video_id;

    const statusBadge = badge(video.status);

    const playBtn = document.createElement("button");
    playBtn.textContent = "Play";
    playBtn.disabled = video.status !== "Ready";
    playBtn.addEventListener("click", () => onPlay(video));

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "secondary";
    deleteBtn.textContent = "Delete";
    deleteBtn.addEventListener("click", () => onDelete(video));

    li.append(title, statusBadge, playBtn, deleteBtn);
    els.gallery.append(li);
  }
}

async function refreshGallery() {
  try {
    const videos = await listVideos();
    renderGallery(videos);
  } catch (err) {
    console.error(err);
  }
}

async function onPlay(video) {
  els.playerSection.hidden = false;
  els.playerTitle.textContent = `Now playing: ${video.title || video.original_filename || video.video_id}`;
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

async function onDelete(video) {
  try {
    await deleteVideo(video.video_id);
    await refreshGallery();
  } catch (err) {
    console.error(err);
  }
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
    await refreshGallery();
  } catch (err) {
    els.uploadStatus.textContent = "Upload failed.";
    console.error(err);
  } finally {
    els.uploadButton.disabled = false;
  }
}

async function init() {
  config = await loadConfig();
  els.uploadForm.addEventListener("submit", onUploadSubmit);
  await refreshGallery();
  setInterval(refreshGallery, POLL_INTERVAL_MS);
}

init().catch((err) => {
  console.error(err);
  els.uploadStatus.textContent = "Failed to initialize the app.";
});
