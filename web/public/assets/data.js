// Renders the latest published bulk-data snapshot on /data/.
// Same-origin fetch of public snapshot metadata; connect-src 'self' suffices.
(async () => {
  const el = document.getElementById("snapshot");
  if (!el) return;
  try {
    const res = await fetch("/v1/snapshots/latest");
    if (res.status === 404) {
      el.innerHTML =
        "<p class='status'>No public snapshot has been published yet. Check back soon.</p>";
      return;
    }
    if (!res.ok) throw new Error("HTTP " + res.status);
    const s = await res.json();
    const formats = Array.isArray(s.formats) ? s.formats : [];
    const rows = formats
      .filter((f) => f.url)
      .map(
        (f) =>
          `<tr><td><code>${f.format || "file"}</code></td>` +
          `<td><a href="${f.url}">${f.url.split("/").pop()}</a></td>` +
          `<td class="status">${f.checksum ? f.checksum.slice(0, 12) + "…" : ""}</td></tr>`
      )
      .join("");
    el.innerHTML =
      `<p>Latest version <code>${s.version || "unknown"}</code>` +
      (s.published_at ? `, published ${new Date(s.published_at).toUTCString()}` : "") +
      `.</p>` +
      (rows
        ? `<table class="snapshot"><thead><tr><th>Format</th><th>Download</th><th>Checksum</th></tr></thead><tbody>${rows}</tbody></table>`
        : "<p class='status'>Snapshot metadata contained no downloadable files.</p>");
  } catch (err) {
    el.innerHTML =
      "<p class='status'>Could not load snapshot metadata. Try the API directly: " +
      "<code>GET /v1/snapshots/latest</code>.</p>";
  }
})();
