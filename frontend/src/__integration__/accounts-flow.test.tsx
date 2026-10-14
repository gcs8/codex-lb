import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import App from "@/App";
import { createAccountSummary } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/utils";

describe("accounts flow integration", () => {
  it("derives distributions only from the scoped API inventory and preserves response statuses", async () => {
    const user = userEvent.setup({ delay: null });
    server.use(http.get("/api/accounts", () => HttpResponse.json({
      accounts: [
        createAccountSummary({
          accountId: "visible-pro", email: "visible-pro@example.com", displayName: "visible-pro@example.com", planType: "pro",
          status: "paused", usage: { primaryRemainingPercent: 100, secondaryRemainingPercent: 100 },
        }),
        createAccountSummary({
          accountId: "visible-custom", email: "visible-custom@example.com", displayName: "visible-custom@example.com", planType: "future_plan",
          status: "active", usage: { primaryRemainingPercent: 0, secondaryRemainingPercent: 0 },
        }),
      ],
    })));
    window.history.pushState({}, "", "/accounts");
    renderWithProviders(<App />);

    const plans = within(await screen.findByRole("region", { name: "Accounts by plan" }));
    const statuses = within(screen.getByRole("region", { name: "Accounts by status" }));
    expect(plans.getByTestId("donut-center-total")).toHaveTextContent(/^2$/);
    expect(plans.getByRole("button", { name: "pro 1 (50%)" })).toBeInTheDocument();
    expect(plans.getByRole("button", { name: "future_plan 1 (50%)" })).toBeInTheDocument();
    expect(plans.getAllByRole("button")).toHaveLength(2);
    expect(statuses.getByRole("button", { name: "Active 1 (50%)" })).toBeInTheDocument();
    expect(statuses.getByRole("button", { name: "Paused 1 (50%)" })).toBeInTheDocument();
    expect(statuses.getAllByRole("button")).toHaveLength(2);
    expect(screen.queryByText("primary@example.com")).not.toBeInTheDocument();
    expect(screen.queryByText("secondary@example.com")).not.toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Search accounts..."), "not-in-this-scope");
    expect(screen.getByText("No matching accounts")).toBeInTheDocument();
    expect(plans.getByTestId("donut-center-total")).toHaveTextContent(/^2$/);
    expect(statuses.getByTestId("donut-center-total")).toHaveTextContent(/^2$/);
  });

  it("supports account selection and pause/resume actions", async () => {
    const user = userEvent.setup({ delay: null });

    window.history.pushState({}, "", "/accounts");
    renderWithProviders(<App />);

    expect(await screen.findByRole("heading", { name: "Accounts" })).toBeInTheDocument();
    expect((await screen.findAllByText("primary@example.com")).length).toBeGreaterThan(0);
    expect(screen.getByText("secondary@example.com")).toBeInTheDocument();

    await user.click(screen.getByText("secondary@example.com"));
    expect(await screen.findByText("Token Status")).toBeInTheDocument();

    const resumeButton = screen.queryByRole("button", { name: "Resume" });
    if (resumeButton) {
      await user.click(resumeButton);
      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
      });
    } else {
      await user.click(screen.getByRole("button", { name: "Pause" }));
      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
      });
    }
  });

  it("lets operators set, search, and clear an account alias", async () => {
    const user = userEvent.setup({ delay: null });

    window.history.pushState({}, "", "/accounts");
    renderWithProviders(<App />);

    expect(await screen.findByRole("heading", { name: "Accounts" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Edit alias" }));
    const aliasInput = await screen.findByLabelText("Account alias");
    await user.clear(aliasInput);
    await user.type(aliasInput, "Personal Plus");
    await user.click(screen.getByRole("button", { name: "Save alias" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Personal Plus" })).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText("Search accounts..."), "personal");
    expect(screen.getAllByText("Personal Plus").length).toBeGreaterThan(0);
    expect(screen.queryByText("secondary@example.com")).not.toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "Edit alias" }));
    const aliasInputToClear = await screen.findByLabelText("Account alias");
    await user.clear(aliasInputToClear);
    await user.click(screen.getByRole("button", { name: "Save alias" }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "primary@example.com" })).toBeInTheDocument();
    });
  });
});
