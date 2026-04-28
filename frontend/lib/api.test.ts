import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "./api";

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("routes FastAPI requests through the same-origin backend proxy", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/me", { headers: { Accept: "application/json" } });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/api/me",
      expect.objectContaining({
        credentials: "include",
        headers: { Accept: "application/json" },
      }),
    );
  });

  it("keeps an explicit credentials override", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/me", { credentials: "omit" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/backend/api/me",
      expect.objectContaining({ credentials: "omit" }),
    );
  });
});
