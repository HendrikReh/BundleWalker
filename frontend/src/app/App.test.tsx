import { render, screen } from "@testing-library/react";
import { test } from "vitest";

import { App } from "./App";

test("renders the local review cockpit shell", () => {
  render(<App />);

  screen.getByRole("heading", { name: "Local review cockpit" });
  screen.getByRole("complementary", { name: "Workspace" });
});
