import { expect, it } from "vitest";
import { ForecastVsActualPage } from "./ForecastVsActualPage";
import { PlayerForecastVsActualPage } from "./PlayerForecastVsActualPage";

it("keeps the historical source alias bound to the current player page", () => {
  expect(ForecastVsActualPage).toBe(PlayerForecastVsActualPage);
});
