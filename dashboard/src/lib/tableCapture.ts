// Browser-only presentation export. Never fetch a forecast or submit a plan.
export interface TableCaptureInfo {
  title: string;
  context?: string;
  capturedAt: string;
}

export interface TableCapture {
  blob: Blob;
  width: number;
  height: number;
  filename: string;
}

/** Clone the currently rendered rows, including their order and expanded details.
 * Pagination is intentional: capture the current page, never unseen player rows.
 * Inline computed styles retain page-scoped themes without mutating the live table.
 */
export function cloneCaptureContent(source: HTMLElement): HTMLElement {
  const clone = source.cloneNode(true) as HTMLElement;
  const originals = [source, ...source.querySelectorAll<HTMLElement | SVGElement>("*")];
  const copies = [clone, ...clone.querySelectorAll<HTMLElement | SVGElement>("*")];
  originals.forEach((element, index) => {
    const copy = copies[index];
    if (copy !== clone && !clone.contains(copy)) return;
    const style = getComputedStyle(element);
    // Computed longhands already resolve theme variables. Copying the complete
    // theme again on every cell bloats large tables; assign resolved styles once.
    copy.style.cssText = Array.from(style)
      .filter(key => !key.startsWith("--"))
      .map(key => `${key}:${style.getPropertyValue(key)};`).join("");
    copy.removeAttribute("id");
    copy.removeAttribute("autofocus");
    for (const attr of Array.from(copy.attributes)) {
      if (attr.name.startsWith("on")) copy.removeAttribute(attr.name);
    }
    if (element.matches("script, iframe, object, embed, [data-capture-exclude], input[type=password], input[type=hidden]") ||
        style.display === "none" || style.visibility === "hidden" || element.classList.contains("sr-only")) {
      copy.remove();
      return;
    }
    if (style.position === "sticky" || style.position === "fixed") {
      copy.style.position = "static";
      copy.style.inset = "auto";
    }
    if (element.querySelector("table")) {
      // Computed pixel heights on non-scrolling flex ancestors otherwise leave
      // the export footer halfway through a long player table.
      copy.style.height = "auto";
      copy.style.maxHeight = "none";
      copy.style.minHeight = "0";
      copy.style.flex = "0 0 auto";
    }
    // Expand every scroll container, not just the viewport's visible rectangle.
    if (/(auto|scroll|hidden|clip)/.test(style.overflow + style.overflowX + style.overflowY)) {
      copy.style.maxHeight = "none";
      copy.style.height = "auto";
      copy.style.maxWidth = "none";
      copy.style.width = `${Math.max(element.scrollWidth, element.getBoundingClientRect().width)}px`;
      copy.style.overflow = "visible";
      copy.style.flexShrink = "0";
    }
    // Preserve user selections, not the input's initial HTML attributes.
    if (element instanceof HTMLInputElement && copy instanceof HTMLInputElement) {
      copy.value = element.value;
      copy.checked = element.checked;
    }
    if (element instanceof HTMLSelectElement && copy instanceof HTMLSelectElement) copy.value = element.value;
    if (element instanceof HTMLImageElement && copy instanceof HTMLImageElement) copy.loading = "eager";
  });
  clone.style.height = "auto";
  clone.style.maxHeight = "none";
  clone.style.overflow = "visible";
  return clone;
}

/** Canvas conversion must not wait for requestAnimationFrame: opening the preview
 * can hide the source tab and suspend its animation callbacks indefinitely.
 */
export async function captureSvgToPng(svg: string, width: number, height: number, signal: AbortSignal): Promise<Blob> {
  const image = new Image();
  await new Promise<void>((resolve, reject) => {
    const cleanup = () => { image.onload = null; image.onerror = null; signal.removeEventListener("abort", abort); };
    const abort = () => { cleanup(); image.src = ""; reject(signal.reason); };
    image.onload = () => { cleanup(); resolve(); };
    image.onerror = () => { cleanup(); reject(new Error("The browser could not render this image. Try a smaller table view.")); };
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) { abort(); return; }
    image.src = svg;
  });
  signal.throwIfAborted();
  const canvas = document.createElement("canvas");
  const ratio = Math.min(2, Math.sqrt(16_000_000 / (width * height)));
  canvas.width = Math.ceil(width * ratio);
  canvas.height = Math.ceil(height * ratio);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Image capture is unavailable in this browser.");
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      canvas.width = canvas.height = 0;
      if (blob?.size) resolve(blob);
      else reject(new Error("The browser could not encode this image. Try a smaller table view."));
    }, "image/png");
  });
}

export async function captureTable(source: HTMLElement, info: TableCaptureInfo, progress: (message: string) => void = () => {}): Promise<TableCapture> {
  progress("1/3 · Expanding the full table width and height…");
  // Freeze the DOM before any await: changing a filter during export cannot mix views.
  const content = cloneCaptureContent(source);
  const stage = document.createElement("div");
  stage.inert = true;
  stage.setAttribute("aria-hidden", "true");
  stage.style.cssText = "position:fixed;left:-100000px;top:0;pointer-events:none;z-index:-1;";
  const sheet = document.createElement("div");
  const background = getComputedStyle(document.body).backgroundColor;
  const foreground = getComputedStyle(document.body).color;
  sheet.style.cssText = `padding:24px;box-sizing:border-box;background:${background};color:${foreground};font:14px Arial,sans-serif;width:max-content;min-width:640px;`;
  const heading = document.createElement("header");
  heading.style.cssText = "border-bottom:3px solid #b45309;padding:0 0 16px;margin-bottom:16px;max-width:1100px;";
  const brand = document.createElement("div");
  brand.textContent = "THE COMET · www.thecometfpl.com";
  brand.style.cssText = "font-size:22px;font-weight:800;letter-spacing:2px;color:#b45309;";
  const title = document.createElement("h1");
  title.textContent = info.title;
  title.style.cssText = "font-size:20px;margin:10px 0 6px;";
  const context = document.createElement("p");
  context.textContent = info.context ?? "Current table view · selected filters and display order";
  context.style.cssText = "margin:0;line-height:1.5;overflow-wrap:anywhere;";
  heading.append(brand, title, context);
  const footer = document.createElement("footer");
  footer.style.cssText = "border-top:1px solid #b45309;padding-top:12px;margin-top:18px;font-size:12px;line-height:1.6;";
  footer.textContent = `www.thecometfpl.com · Captured ${info.capturedAt} · Image capture time, not a data refresh. Full table width and height; current page, filters and order preserved.`;
  sheet.append(heading, content, footer);
  stage.append(sheet);
  document.body.append(stage);
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      const error = new Error("Capture took too long. Narrow the table filters and try again; no data was changed.");
      controller.abort(error);
      reject(error);
    }, 20000);
  });
  const render = async () => {
    const { toSvg } = await import("html-to-image");
    controller.signal.throwIfAborted();
    // Size the whole branded sheet around the expanded table, including its right
    // padding; otherwise an overflowed table could end flush against the PNG edge.
    sheet.style.width = `${Math.max(592, content.scrollWidth) + 48}px`;
    content.style.width = "100%";
    const width = Math.ceil(sheet.scrollWidth);
    const height = Math.ceil(sheet.scrollHeight);
    if (width > 16000 || height > 16000 || width * height > 32_000_000) {
      throw new Error("This view is too large for a readable image. Narrow the filters or date range and capture again.");
    }
    progress("2/3 · Creating the image with www.thecometfpl.com watermark…");
    const svg = await toSvg(sheet, {
      width, height,
      // The snapshot already has complete inline computed styles. Do not copy
      // every CSS property a second time for thousands of table elements.
      includeStyleProperties: [],
      preferredFontFormat: "woff2",
      // A blocked decorative CDN badge must not hide the table's text or statistics.
      imagePlaceholder: "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1' height='1'/%3E",
      fetchRequestInit: { credentials: "omit", referrerPolicy: "no-referrer", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]) },
    });
    controller.signal.throwIfAborted();
    progress("3/3 · Preparing your PNG for download and sharing…");
    const blob = await captureSvgToPng(svg, width, height, controller.signal);
    return { blob, width, height, filename: `the-comet-${info.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${info.capturedAt.slice(0, 10)}.png` };
  };
  try {
    return await Promise.race([render(), deadline]);
  } finally {
    clearTimeout(timer);
    stage.remove();
  }
}

/** Only user-selected image bytes are shared. Never include a URL/query, manager
 * identity, storage, request token, or other hidden page context in the share payload.
 */
export function captureShareData(capture: TableCapture, title: string): ShareData {
  return { files: [new File([capture.blob], capture.filename, { type: "image/png" })], title: `THE COMET · ${title}` };
}
