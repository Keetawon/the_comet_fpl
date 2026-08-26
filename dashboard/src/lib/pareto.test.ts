import { describe, expect, it } from "vitest";
import {
  classifyPareto,
  dominates,
  type ParetoDirections,
  type ParetoPoint,
} from "./pareto";

const point = (id: number, x: number | null, y: number | null): ParetoPoint => ({ id, x, y });

describe("dominates", () => {
  it.each<{
    directions: ParetoDirections;
    candidate: ParetoPoint;
    subject: ParetoPoint;
  }>([
    {
      directions: { x: "minimize", y: "maximize" },
      candidate: point(1, 4, 8),
      subject: point(2, 5, 7),
    },
    {
      directions: { x: "maximize", y: "maximize" },
      candidate: point(1, 6, 8),
      subject: point(2, 5, 7),
    },
    {
      directions: { x: "maximize", y: "minimize" },
      candidate: point(1, 6, 6),
      subject: point(2, 5, 7),
    },
    {
      directions: { x: "minimize", y: "minimize" },
      candidate: point(1, 4, 6),
      subject: point(2, 5, 7),
    },
  ])("supports $directions.x/$directions.y", ({ candidate, subject, directions }) => {
    expect(dominates(candidate, subject, directions)).toBe(true);
    expect(dominates(subject, candidate, directions)).toBe(false);
  });

  it("requires a strict improvement and never compares missing coordinates", () => {
    const directions: ParetoDirections = { x: "minimize", y: "maximize" };
    expect(dominates(point(1, 5, 7), point(2, 5, 7), directions)).toBe(false);
    expect(dominates(point(1, null, 8), point(2, 5, 7), directions)).toBe(false);
    expect(dominates(point(1, 4, 8), point(2, Number.NaN, 7), directions)).toBe(false);
  });
});

describe("classifyPareto", () => {
  it("finds a left-and-up frontier without constructing a convex hull", () => {
    const result = classifyPareto(
      [point(30, 4, 6), point(10, 5, 8), point(20, 6, 7), point(40, 7, 10)],
      { x: "minimize", y: "maximize" },
    );

    expect(result.frontier.map(({ id }) => id)).toEqual([10, 30, 40]);
    expect(result.plotted.find(({ point: value }) => value.id === 20)?.isFrontier).toBe(false);
  });

  it("keeps duplicate coordinates as separate frontier members in stable numeric id order", () => {
    const result = classifyPareto(
      [point(20, 5, 8), point(3, 5, 8), point(11, 6, 7)],
      { x: "minimize", y: "maximize" },
    );

    expect(result.plotted.map(({ point: value }) => value.id)).toEqual([3, 11, 20]);
    expect(result.frontier.map(({ id }) => id)).toEqual([3, 20]);
  });

  it("omits null and non-finite values deterministically instead of zero-filling them", () => {
    const result = classifyPareto(
      [
        point(7, Number.POSITIVE_INFINITY, 9),
        point(4, null, 9),
        point(8, 3, Number.NaN),
        point(2, 5, 6),
      ],
      { x: "maximize", y: "maximize" },
    );

    expect(result.plotted.map(({ point: value }) => value.id)).toEqual([2]);
    expect(result.omitted.map(({ id }) => id)).toEqual([4, 7, 8]);
    expect(result.frontier.map(({ id }) => id)).toEqual([2]);
  });

  it("uses a stable string id order and preserves repeated ids by input order", () => {
    const points = [
      { id: "z", x: 1, y: 2, marker: "first" },
      { id: "a", x: 1, y: 2, marker: "alpha" },
      { id: "z", x: 1, y: 2, marker: "second" },
    ];
    const result = classifyPareto(points, { x: "maximize", y: "maximize" });

    expect(result.frontier.map(({ marker }) => marker)).toEqual(["alpha", "first", "second"]);
  });
});
