import { captureShareData, type TableCapture, type TableCaptureInfo } from "./tableCapture";

// Open synchronously from the user's click so popup blockers can be reported before
// any image work. The preview has no network backend, stored draft, or manager URL.
export function openCapturePreview(info: TableCaptureInfo, preferShare: boolean) {
  const preview = window.open("", "_blank", "popup,width=1200,height=850");
  if (!preview) throw new Error("Allow pop-ups for this Dashboard, then capture again.");
  preview.opener = null;
  const doc = preview.document;
  doc.title = `THE COMET · ${info.title} · Capture`;
  doc.documentElement.lang = "en";
  const viewport = doc.createElement("meta");
  viewport.name = "viewport";
  viewport.content = "width=device-width, initial-scale=1";
  doc.head.append(viewport);
  doc.body.style.cssText = "margin:0;background:#f4f4f5;color:#18181b;font:14px/1.5 system-ui,sans-serif;";
  const toolbar = doc.createElement("header");
  toolbar.style.cssText = "position:sticky;top:0;padding:16px 20px;background:white;border-bottom:1px solid #ddd;display:flex;align-items:center;gap:10px;flex-wrap:wrap;z-index:1;";
  const title = doc.createElement("strong");
  title.textContent = "THE COMET · Your capture";
  title.style.marginRight = "auto";
  const status = doc.createElement("p");
  status.setAttribute("role", "status");
  status.style.cssText = "padding:0 20px;";
  status.textContent = "Preparing your current table view…";
  const gallery = doc.createElement("main");
  gallery.style.cssText = "padding:0 20px 24px;overflow:auto;";
  doc.body.append(toolbar, status, gallery);
  toolbar.append(title);
  let url: string | null = null;
  preview.addEventListener("pagehide", () => { if (url) URL.revokeObjectURL(url); }, { once: true });
  return {
    fail(message: string) { if (!preview.closed) status.textContent = message; },
    ready(capture: TableCapture) {
      if (preview.closed) return;
      url = URL.createObjectURL(capture.blob);
      const image = doc.createElement("img");
      image.src = url;
      image.alt = `THE COMET · ${info.title} · current table capture`;
      image.style.cssText = "display:block;max-width:100%;height:auto;margin:0 auto;box-shadow:0 4px 20px #0001;";
      gallery.append(image);
      status.textContent = "Review before sharing. Includes only this table page and its expanded rows. Capture time is not data freshness. Blocked decorative badges may be omitted.";
      const style = "border:1px solid #d4d4d8;border-radius:8px;background:white;color:#18181b;padding:10px 14px;font:inherit;cursor:pointer;text-decoration:none;";
      const download = doc.createElement("a");
      download.textContent = "Download PNG";
      download.href = url;
      download.download = capture.filename;
      download.style.cssText = style;
      const zoom = doc.createElement("button");
      zoom.textContent = "Actual size";
      zoom.style.cssText = style;
      zoom.onclick = () => {
        const full = image.style.maxWidth === "100%";
        image.style.maxWidth = full ? "none" : "100%";
        zoom.textContent = full ? "Fit to window" : "Actual size";
      };
      const share = doc.createElement("button");
      share.textContent = "Share image";
      share.style.cssText = `${style}background:#fef3c7;border-color:#fbbf24;`;
      const data = captureShareData(capture, info.title);
      share.onclick = async () => {
        if (!preview.navigator.canShare?.(data) || !preview.navigator.share) {
          status.textContent = "Image sharing is unavailable in this browser. Use Download PNG, then attach the image in your favourite app.";
          download.focus();
          return;
        }
        try {
          await preview.navigator.share(data);
          status.textContent = "Image handed to your selected sharing app.";
        } catch (error) {
          status.textContent = typeof error === "object" && error !== null && "name" in error && error.name === "AbortError"
            ? "Sharing cancelled. Your image is still available."
            : "Sharing was not completed. You can still download the PNG.";
        }
      };
      toolbar.append(download, zoom, share);
      if (preferShare) share.focus();
    },
  };
}
