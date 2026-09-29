// The signed-out screen at /app (AUTH_MODE=clerk): the landing page's frame around
// Clerk's form, so a bookmark after the session ended still looks like the product.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SignedOutShell } from "../src/app/SignedOutShell";

describe("SignedOutShell", () => {
  it("frames the form with the product name, theme toggle and legal links", () => {
    render(
      <SignedOutShell>
        <form aria-label="clerk form" />
      </SignedOutShell>,
    );
    expect(screen.getByRole("heading", { name: "Sign in or create an account" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "alo reader" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("group", { name: "Colour theme" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Terms & privacy" }).getAttribute("href")).toBe("/legal");
    expect(screen.getByRole("form", { name: "clerk form" })).toBeTruthy();
  });
});
