import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { MultiSelectFilter } from "./MultiSelectFilter";

const OPTIONS = [
  { value: 1, label: "Alpha · ALP · MID" },
  { value: 2, label: "Beta · BET · GK" },
] as const;

function Harness() {
  const [selected, setSelected] = useState<number[]>([]);
  return (
    <MultiSelectFilter
      label="Player"
      ariaLabel="Player name filter"
      allLabel="All players"
      options={OPTIONS}
      selected={selected}
      onChange={setSelected}
      searchable
      searchLabel="Search player names"
    />
  );
}

it("supports searchable checkbox selection, Escape focus restoration, and field clear", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  const trigger = screen.getByRole("button", { name: "Player name filter: All players" });

  await user.click(trigger);
  const search = screen.getByRole("textbox", { name: "Search player names" });
  expect(search).toHaveFocus();
  await user.type(search, "alp");
  const alpha = screen.getByRole("checkbox", { name: /Alpha · ALP · MID/ });
  expect(screen.queryByRole("checkbox", { name: /Beta · BET · GK/ })).not.toBeInTheDocument();

  alpha.focus();
  await user.keyboard(" ");
  expect(alpha).toBeChecked();
  await user.keyboard("{Escape}");
  expect(trigger).toHaveFocus();
  expect(trigger).toHaveAccessibleName("Player name filter: Alpha · ALP · MID");

  await user.click(trigger);
  const reopenedSearch = screen.getByRole("textbox", { name: "Search player names" });
  expect(reopenedSearch).toHaveValue("");
  expect(reopenedSearch).toHaveFocus();
  expect(screen.getByRole("checkbox", { name: /Alpha · ALP · MID/ })).toBeChecked();
  await user.click(screen.getByRole("button", { name: "Clear" }));
  expect(trigger).toHaveTextContent("All players");
});
