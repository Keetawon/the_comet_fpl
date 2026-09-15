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
    const style = getComputedStyle(element);
    for (const key of Array.from(style)) copy.style.setProperty(key, style.getPropertyValue(key));
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

export async function captureTable(source: HTMLElement, info: TableCaptureInfo): Promise<TableCapture> {
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
  brand.textContent = "THE COMET · FPL DASHBOARD";
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
  footer.textContent = `THE COMET · Captured ${info.capturedAt} · Image capture time, not a data refresh. Current table page; filters and order preserved.`;
  sheet.append(heading, content, footer);
  stage.append(sheet);
  document.body.append(stage);
  try {
    const { toBlob } = await import("html-to-image");
    await document.fonts.ready;
    // Size the whole branded sheet around the expanded table, including its right
    // padding; otherwise an overflowed table could end flush against the PNG edge.
    sheet.style.width = `${Math.max(592, content.scrollWidth) + 48}px`;
    content.style.width = "100%";
    const width = Math.ceil(sheet.scrollWidth);
    const height = Math.ceil(sheet.scrollHeight);
    if (width > 16000 || height > 16000 || width * height > 32_000_000) {
      throw new Error("This view is too large for a readable image. Narrow the filters or date range and capture again.");
    }
    const blob = await toBlob(sheet, {
      width, height,
      pixelRatio: Math.min(2, Math.sqrt(16_000_000 / (width * height))),
      preferredFontFormat: "woff2",
      // A blocked decorative CDN badge must not hide the table's text or statistics.
      imagePlaceholder: "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1' height='1'/%3E",
      fetchRequestInit: { credentials: "omit", referrerPolicy: "no-referrer", signal: AbortSignal.timeout(15000) },
    });
    if (!blob || blob.size === 0) throw new Error("The browser could not render this image. Try a smaller table view.");
    return { blob, width, height, filename: `the-comet-${info.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${info.capturedAt.slice(0, 10)}.png` };
  } finally {
    stage.remove();
  }
}

/** Only user-selected image bytes are shared. Never include a URL/query, manager
 * identity, storage, request token, or other hidden page context in the share payload.
 */
export function captureShareData(capture: TableCapture, title: string): ShareData {
  return { files: [new File([capture.blob], capture.filename, { type: "image/png" })], title: `THE COMET · ${title}` };
}
