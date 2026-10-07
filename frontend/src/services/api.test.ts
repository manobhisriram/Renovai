import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuth } from "../stores/auth";
import { ApiError, api, errorMessage } from "./api";

const caught = (p: Promise<unknown>) => p.then(() => { throw new Error("expected a rejection"); }, (e: ApiError) => e);

const user = { id: "u", email: "a@b.co", full_name: "A", role: "admin" as const, is_active: true };
const respond = (status: number, body: unknown) => vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

describe("api client", () => {
  beforeEach(() => { sessionStorage.clear(); useAuth.getState().signIn("tok123", user); });
  afterEach(() => vi.restoreAllMocks());

  it("sends the bearer token and JSON body", async () => {
    const f = respond(200, { ok: 1 });
    vi.stubGlobal("fetch", f);
    await api.post("/x", { a: 1 });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/v1/x");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok123");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(init.body).toBe('{"a":1}');
  });

  it("turns structured server errors into ApiError with request id and field details", async () => {
    vi.stubGlobal("fetch", respond(422, { error: { code: "validation_failed", message: "Some fields are invalid.", request_id: "rid1", details: { fields: [{ field: "area_sqm", message: "must be > 0" }] } } }));
    const err = await caught(api.get("/x"));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(errorMessage(err)).toContain("area_sqm: must be > 0");
    expect(errorMessage(err)).toContain("rid1");
  });

  it("signs the user out on 401", async () => {
    vi.stubGlobal("fetch", respond(401, { error: { code: "unauthorized", message: "Sign in to continue." } }));
    await api.get("/x").catch(() => undefined);
    expect(useAuth.getState().token).toBeNull();
    expect(sessionStorage.getItem("renovai.session")).toBeNull();
  });

  it("reports network failures in plain language", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await caught(api.get("/x"));
    expect(err.code).toBe("network");
    expect(errorMessage(err)).toMatch(/Cannot reach the server/);
  });

  it("handles 204 responses and non-JSON error bodies", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(api.del("/x")).resolves.toBeUndefined();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 })));
    const err = await caught(api.get("/x"));
    expect(err.message).toBe("Request failed (502).");
  });
});
