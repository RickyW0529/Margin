import { describe, expect, it } from "vitest";

import { detectProviderLabel } from "./provider-settings";

describe("provider settings detection", () => {
  it("detects ModelScope and local OpenAI-compatible LLM URLs", () => {
    expect(
      detectProviderLabel("llm", "https://api-inference.modelscope.cn/v1/"),
    ).toMatchObject({ providerId: "modelscope", label: "ModelScope" });
    expect(
      detectProviderLabel("llm", "http://localhost:11434/v1"),
    ).toMatchObject({ providerId: "ollama", label: "Ollama" });
    expect(
      detectProviderLabel("llm", "http://127.0.0.1:8000/v1"),
    ).toMatchObject({ providerId: "vllm", label: "VLLM" });
  });
});
