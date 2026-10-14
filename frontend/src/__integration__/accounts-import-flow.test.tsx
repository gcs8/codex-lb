import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/utils";

describe("accounts import route integration", () => {
  beforeEach(async () => {
    // jsdom's File/FormData cannot be serialized by Node's fetch. Use the
    // constructors from the fetch realm without replacing fetch or the API.
    const formData = await new Request("http://localhost/api/accounts/import", {
      method: "POST",
      headers: { "Content-Type": "multipart/form-data; boundary=fixture-realm" },
      body: '--fixture-realm\r\nContent-Disposition: form-data; name="file"; filename="fixture.json"\r\nContent-Type: application/json\r\n\r\n{}\r\n--fixture-realm--\r\n',
    }).formData();
    const file = formData.get("file");
    if (!file || typeof file === "string") {
      throw new Error("Fetch realm fixture did not produce a File");
    }
    vi.stubGlobal("FormData", formData.constructor);
    vi.stubGlobal("File", file.constructor);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([400, 403])("retains the pending batch after a %s refusal and retries without duplicating success", async (status) => {
    const user = userEvent.setup({ delay: null });
    const attempted: string[] = [];
    let refuse = true;
    server.use(
      http.post("/api/accounts/import", async ({ request }) => {
        expect(request.headers.get("content-type")).toMatch(/^multipart\/form-data; boundary=/);
        const body = await request.text();
        expect(body.match(/name="auth_json"/g)).toHaveLength(1);
        expect(body).toContain("\r\n\r\n{}\r\n");
        const name = /filename="([^"]+)"/.exec(body)?.[1];
        expect(name).toBeDefined();
        attempted.push(name!);
        if (name === "second.json" && refuse) {
          return HttpResponse.json(
            { error: { code: status === 403 ? "read_only_access" : "invalid_auth_json", message: "Synthetic import refusal" } },
            { status },
          );
        }
        return HttpResponse.json({
          accountId: `synthetic-${name}`,
          email: "synthetic@example.com",
          planType: "plus",
          status: "active",
        });
      }),
    );
    window.history.pushState({}, "", "/accounts");
    const { queryClient } = renderWithProviders(<App />);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    expect(await screen.findByRole("heading", { name: "Accounts" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Add account" }));
    await user.click(await screen.findByRole("button", { name: /Import/ }));
    const dialog = await screen.findByRole("dialog", { name: "Import account" });
    const files = ["first.json", "second.json", "third.json"].map((name) =>
      new File(["{}"], name, { type: "application/json" }),
    );
    await user.upload(within(dialog).getByLabelText(/auth\.json files/i), files);
    await user.click(within(dialog).getByRole("button", { name: "Import" }));
    await within(dialog).findByText("Synthetic import refusal");
    expect(queryClient.getMutationCache().getAll().find((mutation) => mutation.state.status === "error")?.state.error).toMatchObject({
      status,
      code: status === 403 ? "read_only_access" : "invalid_auth_json",
      message: "Synthetic import refusal",
    });
    expect(attempted).toEqual(["first.json", "second.json"]);
    expect(within(dialog).queryByText("first.json")).not.toBeInTheDocument();
    expect(within(dialog).getByText("second.json")).toBeInTheDocument();
    expect(within(dialog).getByText("third.json")).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["accounts", "list"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard", "overview"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard", "projections"] });
    refuse = false;
    await user.click(within(dialog).getByRole("button", { name: "Import" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Import account" })).not.toBeInTheDocument());
    expect(attempted).toEqual(["first.json", "second.json", "second.json", "third.json"]);
    expect(invalidate.mock.calls.filter(([filter]) => filter?.queryKey?.join("/") === "accounts/list")).toHaveLength(3);
    invalidate.mockRestore();
  });
});
