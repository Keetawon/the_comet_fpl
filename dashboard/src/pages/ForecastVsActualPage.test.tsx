import { expect, it } from "vitest";
import { ForecastVsActualPage } from "./ForecastVsActualPage";
import { PlayerForecastVsActualPage } from "./PlayerForecastVsActualPage";

it("keeps the historical source alias bound to the schema-v6 player page", () => {
  expect(ForecastVsActualPage).toBe(PlayerForecastVsActualPage);
});
