// player.js — HLS playback via hls.js (loaded from the CDN as the global `Hls`).
//
// Production playback is same-origin under the one CloudFront domain, so the
// CloudFront signed cookies attach to hls.js's segment XHRs automatically — we
// set NO withCredentials/xhrSetup. Local-dev playback (signed-url mode) is just
// a different URL the API returns (a rewritten playlist whose segment lines are
// absolute signed URLs); the player loads it identically.
//
// On a segment 403 (cookies/URL expired) we call onRefresh() to re-fetch a fresh
// play-url, then reload the source and resume.

function supportsNativeHls(videoEl) {
  return videoEl.canPlayType("application/vnd.apple.mpegurl") !== "";
}

export function destroyPlayer(videoEl) {
  if (videoEl._hls) {
    videoEl._hls.destroy();
    videoEl._hls = null;
  }
}

// play(videoEl, playUrl, { onRefresh }) -> starts playback of the playlist.
// onRefresh: optional async () => string, returns a fresh playlist URL when a
// segment request is rejected with 403.
export function play(videoEl, playUrl, { onRefresh } = {}) {
  destroyPlayer(videoEl);

  const Hls = window.Hls;
  if (Hls && Hls.isSupported()) {
    let refreshing = false;
    const hls = new Hls({ enableWorker: true });
    videoEl._hls = hls;

    const refresh = async () => {
      if (refreshing || typeof onRefresh !== "function") {
        return false;
      }
      refreshing = true;
      try {
        const freshUrl = await onRefresh();
        hls.loadSource(freshUrl);
        hls.startLoad();
        return true;
      } finally {
        refreshing = false;
      }
    };

    hls.on(Hls.Events.ERROR, (event, data) => {
      const code = data.response && data.response.code;
      if (code === 403) {
        // Expired signed cookies / URL — refresh and resume.
        refresh();
        return;
      }
      if (!data.fatal) {
        return;
      }
      switch (data.type) {
        case Hls.ErrorTypes.NETWORK_ERROR:
          hls.startLoad();
          break;
        case Hls.ErrorTypes.MEDIA_ERROR:
          hls.recoverMediaError();
          break;
        default:
          destroyPlayer(videoEl);
          break;
      }
    });

    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      videoEl.play().catch(() => {
        /* autoplay can be blocked; the user can press play */
      });
    });

    hls.loadSource(playUrl);
    hls.attachMedia(videoEl);
    return;
  }

  if (supportsNativeHls(videoEl)) {
    // Safari plays HLS natively; same-origin cookies still attach automatically.
    videoEl.src = playUrl;
    videoEl.addEventListener(
      "loadedmetadata",
      () => {
        videoEl.play().catch(() => {});
      },
      { once: true },
    );
    return;
  }

  throw new Error("HLS playback is not supported in this browser");
}
