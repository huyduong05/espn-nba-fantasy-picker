import { afterEach, describe, expect, it, vi } from "vitest";

import { requestMetadata, requestRecommendations } from "../src/background.js";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("local API client", () => {
  it("keeps actionable API errors from the local service", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "UNPROCESSABLE_DRAFT_STATE",
              message: "Board issue",
            },
          }),
          { status: 422 },
        ),
      ),
    );

    await expect(
      requestRecommendations({ type: "recommend", draft_state: {} as never }),
    ).resolves.toEqual({
      ok: false,
      code: "UNPROCESSABLE_DRAFT_STATE",
      message: "Board issue",
    });
  });

  it("turns aborted local requests into a timeout result", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue({ name: "AbortError" }));

    await expect(requestMetadata()).resolves.toMatchObject({
      ok: false,
      code: "SERVICE_TIMEOUT",
    });
  });
});
