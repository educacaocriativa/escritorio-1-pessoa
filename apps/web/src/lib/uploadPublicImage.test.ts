import { beforeEach, describe, expect, it, vi } from "vitest";

// Mocka o cliente axios único da aplicação (a instância `api`). baseURL "/api" espelha lib/api.ts.
vi.mock("./api", () => ({
  api: {
    defaults: { baseURL: "/api" },
    post: vi.fn(),
  },
}));

import { api } from "./api";
import { uploadPublicImage } from "./uploadPublicImage";

describe("uploadPublicImage (Story 4.2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("envia multipart para /attachments/public-images e devolve a URL prefixada com /api", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { id: "img-1", url: "/public-images/img-1" } });
    const file = new File([new Uint8Array([1, 2, 3])], "logo.png", { type: "image/png" });

    const url = await uploadPublicImage(file);

    // A URL persistida/renderável precisa passar pelo proxy /api (Vite/Caddy removem o prefixo).
    expect(url).toBe("/api/public-images/img-1");

    expect(api.post).toHaveBeenCalledTimes(1);
    const [path, body, config] = vi.mocked(api.post).mock.calls[0];
    expect(path).toBe("/attachments/public-images");
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("file")).toBe(file);
    expect(config?.headers?.["Content-Type"]).toBe("multipart/form-data");
  });

  it("propaga erro do backend (ex.: 415 tipo não permitido)", async () => {
    vi.mocked(api.post).mockRejectedValue(new Error("415"));
    const file = new File([new Uint8Array([1])], "x.gif", { type: "image/gif" });
    await expect(uploadPublicImage(file)).rejects.toThrow("415");
  });
});
