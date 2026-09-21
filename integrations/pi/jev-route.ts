import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { runCli } from "./process.mjs";

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "jev_route",
    label: "Jev route decision",
    description: "Select one allowed label with Jev and confidence-gated fallback. Does not execute actions or replace your generative model.",
    parameters: Type.Object({
      state: Type.Union([Type.String(), Type.Record(Type.String(), Type.Unknown()), Type.Array(Type.Unknown())]),
      criteria: Type.Record(Type.String(), Type.String(), { minProperties: 1, maxProperties: 255 }),
      instructions: Type.String({ minLength: 1 }),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, _ctx) {
      const result = await runCli(params, signal);
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: {} };
    },
  });
}
