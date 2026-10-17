import { useEffect, useRef, useState } from "react";
import { Check, Copy, Download, MessageSquareText, Share2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { copyGwBriefing, downloadGwBriefing, gwBriefingLineUrl, prepareGwBriefingFacebook, shareGwBriefing } from "@/lib/gwBriefingShare";
import "./ShareBriefing.css";
type Language = "en" | "th";

/** Read-only public text. Users edit their copy in their own app, never this page. */
export function ShareBriefing({ text, language, title }: { text: string; language: Language; title?: string }) {
  const [feedback, setFeedback] = useState("");
  const [copied, setCopied] = useState(false);
  const [facebook, setFacebook] = useState<{ url: string; instruction: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const version = useRef(0);
  useEffect(() => () => { version.current += 1; }, []);
  const lineUrl = text.trim() ? gwBriefingLineUrl(text) : null;
  const act = async (action: "copy" | "share" | "facebook" | "download") => {
    if (!text.trim() || busy) return;
    const current = ++version.current;
    setBusy(true); setFeedback(""); setFacebook(null); setCopied(false);
    try {
      let message = "";
      if (action === "copy") { await copyGwBriefing(text); message = language === "th" ? "คัดลอกแล้ว นำไปวางและแก้ไขในแอปที่คุณใช้ได้เลย" : "Copied. Paste and edit in your favourite app."; }
      else if (action === "share") {
        const result = await shareGwBriefing(text);
        message = result === "shared" ? "Opened sharing app." : result === "copied" ? "Copied. Paste in your favourite app." : "Sharing cancelled.";
      } else if (action === "facebook") {
        const prepared = await prepareGwBriefingFacebook(text);
        if (current === version.current) setFacebook(prepared);
        message = prepared.instruction;
      } else { downloadGwBriefing(text); message = "Text download started."; }
      if (current === version.current) { setFeedback(message); setCopied(action === "copy"); }
    } catch (error) {
      if (current === version.current) setFeedback(error instanceof Error ? error.message : "Sharing is unavailable. Download the text instead.");
    } finally { if (current === version.current) setBusy(false); }
  };
  return <section id="matchweek-analysis" aria-labelledby="analysis-heading" className="comet-glass overflow-hidden rounded-2xl border shadow-sm">
    <div className="border-b p-5 sm:p-6">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground"><MessageSquareText className="size-4" aria-hidden="true" />The Comet briefing</div>
      <h2 id="analysis-heading" className="text-xl font-semibold tracking-tight">{title ?? (language === "th" ? "บทสรุปพร้อมแชร์" : "Your matchweek, in words")}</h2>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{language === "th" ? "คัดลอกทั้งข้อความ แล้วเพิ่มมุมมองของคุณใน LINE, Facebook หรือแอปที่ใช้ได้เลย" : "Copy the full post. Add your own take in LINE, Facebook or your notes app."}</p>
    </div>
    <div className="p-5 sm:p-6">
      <label htmlFor="score-analysis-text" className="sr-only">Analysis message</label>
      <textarea id="score-analysis-text" readOnly lang={language} value={text} className="briefing-message min-h-80 w-full resize-y rounded-xl border bg-muted/30 p-4 text-sm leading-7 focus-visible:outline-2 focus-visible:outline-offset-2 sm:min-h-[26rem]" />
      <div className="mt-4 flex flex-wrap gap-2" aria-label="Share analysis">
        <Button className="min-h-11 gap-2" disabled={busy || !text} onClick={() => { void act("copy"); }}>{copied ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}{copied ? "Copied" : "Copy text"}</Button>
        <Button className="min-h-11 gap-2" variant="outline" disabled={busy || !text} onClick={() => { void act("share"); }}><Share2 className="size-4" aria-hidden="true" />Share</Button>
        {lineUrl && <Button className="min-h-11" variant="outline" asChild><a href={lineUrl} target="_blank" rel="noopener noreferrer">LINE</a></Button>}
        <Button className="min-h-11" variant="ghost" disabled={busy || !text} onClick={() => { void act("facebook"); }}>Copy for Facebook</Button>
        <Button className="min-h-11 gap-2" variant="ghost" disabled={busy || !text} onClick={() => { void act("download"); }}><Download className="size-4" aria-hidden="true" />TXT</Button>
      </div>
      {!lineUrl && <p className="mt-2 text-xs text-muted-foreground">For this longer post, use Copy text or Share to send the full message to LINE.</p>}
      <div className="mt-2 text-sm" role="status" aria-live="polite">{feedback}{facebook && <a href={facebook.url} target="_blank" rel="noopener noreferrer" className="mt-2 block font-medium underline underline-offset-4">Open Facebook and paste</a>}</div>
    </div>
  </section>;
}

