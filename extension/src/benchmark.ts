import { serverMessage, validateRecommendationResponse } from "./api.js";
import {
  PHASE10_SCENARIOS,
  boardForOverallPick,
} from "./benchmark-fixtures.js";
import type { ManualBoardState, PlayerIndex } from "./contracts.js";
import { deriveDraftState, searchPlayers } from "./manual-board.js";
import { renderRecommendations } from "./panel.js";

const SAMPLES_PER_SCENARIO = 30;
interface SampleTiming {
  search_ms: number;
  board_derivation_ms: number;
  json_transfer_ms: number;
  api_round_trip_ms: number;
  server_scoring_ms: number;
  rendering_ms: number;
  total_ms: number;
}

const run = document.querySelector("#run") as HTMLButtonElement;
const status = document.querySelector("#status") as HTMLParagraphElement;
const results = document.querySelector("#results") as HTMLPreElement;

run.addEventListener("click", () => void runBenchmark());

async function runBenchmark(): Promise<void> {
  run.disabled = true;
  status.textContent = "Loading the local player index…";
  results.textContent = "";
  try {
    const index = await loadIndex();
    const scenarioResults: Record<string, SampleTiming[]> = {};
    for (const scenario of PHASE10_SCENARIOS) {
      status.textContent = `Running ${scenario.name} samples…`;
      const board = boardForOverallPick(index, scenario.overallPick);
      const timings: SampleTiming[] = [];
      scenarioResults[scenario.name] = timings;
      for (let sample = 0; sample < SAMPLES_PER_SCENARIO; sample += 1) {
        timings.push(await benchmarkSample(index, board));
      }
    }
    const output = {
      generated_at: new Date().toISOString(),
      samples_per_scenario: SAMPLES_PER_SCENARIO,
      scenarios: Object.fromEntries(
        Object.entries(scenarioResults).map(([name, timings]) => [
          name,
          summarize(timings),
        ]),
      ),
    };
    results.textContent = JSON.stringify(output, null, 2);
    status.textContent =
      "Benchmark complete. Copy the JSON results into the Phase 10 record.";
  } catch (error) {
    status.textContent =
      error instanceof Error ? error.message : "Benchmark failed.";
  } finally {
    run.disabled = false;
  }
}

async function benchmarkSample(
  index: PlayerIndex,
  board: ManualBoardState,
): Promise<SampleTiming> {
  const started = performance.now();
  const searchStarted = performance.now();
  searchPlayers(index, index.players[0]!.display_name);
  const searchMs = performance.now() - searchStarted;

  const derivationStarted = performance.now();
  const derived = deriveDraftState(index, board);
  const boardDerivationMs = performance.now() - derivationStarted;
  if (!derived.ok) {
    throw new Error(`Benchmark board is invalid: ${derived.message}`);
  }

  const serializationStarted = performance.now();
  JSON.stringify(derived.draftState);
  const jsonTransferMs = performance.now() - serializationStarted;
  const apiStarted = performance.now();
  const workerValue = await chrome.runtime.sendMessage({
    type: "recommend",
    draft_state: derived.draftState,
  });
  const apiRoundTripMs = performance.now() - apiStarted;
  const workerResponse = serverMessage(workerValue);
  if (!workerResponse.ok) {
    throw new Error(workerResponse.message);
  }
  const response = validateRecommendationResponse(workerResponse.response);
  if (!response) {
    throw new Error(
      "The local service returned an invalid recommendation response.",
    );
  }

  const renderingStarted = performance.now();
  renderRecommendations(document, document.createElement("div"), response);
  const renderingMs = performance.now() - renderingStarted;
  return {
    search_ms: round(searchMs),
    board_derivation_ms: round(boardDerivationMs),
    json_transfer_ms: round(jsonTransferMs),
    api_round_trip_ms: round(apiRoundTripMs),
    server_scoring_ms: response.latency_ms,
    rendering_ms: round(renderingMs),
    total_ms: round(performance.now() - started),
  };
}

function summarize(
  samples: SampleTiming[],
): Record<string, { p50: number; p95: number }> {
  const fields = Object.keys(samples[0]!) as Array<keyof SampleTiming>;
  return Object.fromEntries(
    fields.map((field) => {
      const values = samples.map((sample) => sample[field]);
      return [
        field,
        { p50: percentile(values, 0.5), p95: percentile(values, 0.95) },
      ];
    }),
  );
}

function percentile(values: number[], ratio: number): number {
  const ordered = [...values].sort((left, right) => left - right);
  return round(ordered[Math.ceil(ratio * ordered.length) - 1]!);
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

async function loadIndex(): Promise<PlayerIndex> {
  const response = await fetch(chrome.runtime.getURL("player-index.json"));
  const value: unknown = await response.json();
  if (
    !response.ok ||
    typeof value !== "object" ||
    value === null ||
    !Array.isArray((value as PlayerIndex).players)
  ) {
    throw new Error(
      "The bundled player index is missing or invalid. Rebuild the extension.",
    );
  }
  return value as PlayerIndex;
}
