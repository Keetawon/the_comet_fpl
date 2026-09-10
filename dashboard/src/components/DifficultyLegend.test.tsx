import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DifficultyLegend } from "./DifficultyLegend";
import type { ColorSource } from "@/lib/difficulty";

function Legend() {
  const [source, setSource] = useState<ColorSource>("opponent");
  return (
    <DifficultyLegend
      colorSource={source}
      onColorSourceChange={setSource}
      easeIndexFormulaVersion="fixture-ease-v1"
      defenceScaleNote="Players defence colours use club defence ease."
    />
  );
}

describe("DifficultyLegend explanations", () => {
  it.each([
    ["Opponent strength", "100 = average club"],
    ["Club ease", "Players defence colours use club defence ease."],
    ["Official FDR", "1 = easiest … 5 = hardest"],
  ])("explains %s on hover without selecting it or hiding the scale", async (label, explanation) => {
    const user = userEvent.setup();
    render(<Legend />);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(screen.queryByText(explanation, { exact: false })).not.toBeInTheDocument();

    const button = screen.getByRole("radio", { name: label });
    await user.hover(button);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent(explanation);
    expect(button).toHaveAttribute("aria-describedby", tooltip.id);
    expect(screen.getByRole("radio", { name: "Opponent strength" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Opponent strength" })).toHaveAttribute("data-state", "on");
    expect(screen.getByText("<= 85 weak opponent")).toHaveClass("bg-green-600");

    // Move beyond Radix's hover bridge (jsdom gives trigger/content zero-size bounds).
    await user.unhover(button);
    fireEvent(document.body, new MouseEvent("pointermove", {
      bubbles: true,
      clientX: 500,
      clientY: 500,
    }));
    await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
  });

  it("supports keyboard focus and Escape while retaining source selection and its colour scale", async () => {
    const user = userEvent.setup();
    render(<Legend />);
    await user.tab();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("100 = average club");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());

    await user.keyboard("{ArrowRight}");
    expect(await screen.findByRole("tooltip")).toHaveTextContent("fixture-ease-v1");
    await user.keyboard(" ");
    expect(screen.getByRole("radio", { name: "Club ease" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Club ease" })).toHaveAttribute("data-state", "on");
    expect(screen.getByText("> 120 much easier")).toHaveClass("bg-green-600");

    await user.click(screen.getByRole("radio", { name: "Official FDR" }));
    expect(screen.getByRole("radio", { name: "Official FDR" })).toBeChecked();
    expect(screen.getByText("FDR 5 hardest")).toHaveClass("bg-red-600");
  });
});
