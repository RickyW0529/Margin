/**
 * @fileoverview Tests for the evidence locator list.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { EvidenceLocatorList } from "./evidence-locator-list";

afterEach(() => {
  cleanup();
});

describe("EvidenceLocatorList", () => {
  it("renders escaped source titles and locator metadata", () => {
    const { container } = render(
      <EvidenceLocatorList
        evidence={[
          {
            evidence_id: "ev-1",
            title: "<img src=x onerror=alert(1)>",
            source_level: "L1",
            locator: "page 3",
            snapshot_id: "snap-1",
          },
        ]}
      />,
    );

    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(screen.getByText("L1")).toBeInTheDocument();
    expect(screen.getByText("page 3")).toBeInTheDocument();
    expect(screen.getByText("snap-1")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
