import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MergeNote } from "@/components/MergeNote";

const html = (props: Parameters<typeof MergeNote>[0]) => renderToStaticMarkup(createElement(MergeNote, props));

// The merge and a tier-2 link are two dated notes (Corey, 2026-10-02): one line each, in one
// note element, so a reader sees where the link's note starts.
describe("MergeNote", () => {
  it("renders nothing without a note", () => {
    expect(html({ text: null })).toBe("");
  });

  it("puts each move on its own line, inside one note element", () => {
    const out = html({ text: "Oct 2, 2026: merged; 2 before, 1 after.\nOct 3, 2026: linked; 1 before, 0 after." });
    expect(out.match(/data-merge-note/g)?.length).toBe(1);
    expect(out).toContain('<span class="block">Oct 2, 2026: merged; 2 before, 1 after.</span>');
    expect(out).toContain('<span class="block">Oct 3, 2026: linked; 1 before, 0 after.</span>');
  });

  it("keeps a one-move note as plain text, and runs moves together inside a line of text", () => {
    expect(html({ text: "Oct 2, 2026: merged." })).not.toContain('class="block"');
    const inline = html({ text: "(a.\nb.)", inline: true });
    expect(inline).toContain(">(a. b.)</span>");
    expect(inline).not.toContain('class="block"');
  });
});
