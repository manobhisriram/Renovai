import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../stores/auth";
import Login from "./Login";
import NewProject from "./NewProject";

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("Login", () => {
  beforeEach(() => { sessionStorage.clear(); useAuth.setState({ token: null, user: null }); });
  afterEach(() => vi.restoreAllMocks());

  it("shows the server's message when credentials are wrong", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(401, { error: { code: "unauthorized", message: "Email or password is incorrect." } })));
    render(<Login />);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is incorrect.");
    expect(useAuth.getState().token).toBeNull();
  });

  it("stores the session on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(200, { access_token: "T", user: { id: "1", email: "a@b.co", full_name: "A", role: "admin", is_active: true } })));
    render(<Login />);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(useAuth.getState().token).toBe("T"));
  });
});

describe("NewProject", () => {
  beforeEach(() => { sessionStorage.clear(); useAuth.setState({ token: "t", user: null }); });
  afterEach(() => vi.restoreAllMocks());
  const setup = () => render(<MemoryRouter><NewProject /></MemoryRouter>);

  it("requires a description or a photo before calling the server", async () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    setup();
    await userEvent.type(screen.getByLabelText("Name"), "Meera");
    await userEvent.click(screen.getByRole("button", { name: "Create and analyse" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Describe the project or add at least one photo.");
    expect(f).not.toHaveBeenCalled();
  });

  it("rejects non-image and oversized files with a clear message", async () => {
    setup();
    const input = screen.getByLabelText("Room photos") as HTMLInputElement;
    await userEvent.upload(input, new File(["x"], "notes.pdf", { type: "application/pdf" }), { applyAccept: false });
    expect(await screen.findByRole("alert")).toHaveTextContent('"notes.pdf" can\'t be used');
    const big = new File([new Uint8Array(9 * 1024 * 1024)], "huge.jpg", { type: "image/jpeg" });
    await userEvent.upload(input, big);
    expect(await screen.findByRole("alert")).toHaveTextContent("huge.jpg");
  });

  it("creates the project, uploads photos, starts the analysis in that order", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string, init: RequestInit) => {
      calls.push(`${init.method} ${url}`);
      if (url.endsWith("/projects")) return json(201, { id: "p9" });
      return json(200, []);
    }));
    setup();
    await userEvent.type(screen.getByLabelText("Name"), "Meera");
    await userEvent.type(screen.getByLabelText("What does the client want?"), "Modern kitchen");
    await userEvent.type(screen.getByLabelText("Floor area (sq ft)"), "120");
    await userEvent.upload(screen.getByLabelText("Room photos"), new File(["abc"], "k.jpg", { type: "image/jpeg" }));
    await userEvent.click(screen.getByRole("button", { name: "Create and analyse" }));
    await waitFor(() => expect(calls).toEqual(["POST /api/v1/projects", "POST /api/v1/projects/p9/images", "POST /api/v1/projects/p9/analyze"]));
  });
});
