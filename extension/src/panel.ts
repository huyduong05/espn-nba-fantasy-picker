import type {
  ManualBoardState,
  PlayerIndex,
  PlayerIndexPlayer,
  RecommendationResponse,
} from "./contracts.js";
import type { Freshness } from "./freshness.js";
import {
  addPlayer,
  emptyBoard,
  removePlayer,
  searchPlayers,
  setDraftSlot,
} from "./manual-board.js";

export interface PanelCallbacks {
  loadBoard: () => Promise<ManualBoardState>;
  saveBoard: (board: ManualBoardState) => Promise<void>;
  suggest: (board: ManualBoardState) => Promise<{
    response: RecommendationResponse;
    freshness: Freshness;
  }>;
}

export interface MountedPanel {
  host: HTMLDivElement;
  destroy: () => void;
}

export function mountPanel(
  document: Document,
  index: PlayerIndex,
  callbacks: PanelCallbacks,
): MountedPanel {
  const host = document.createElement("div");
  host.id = "fantasy-picker-manual-board";
  const shadow = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = styles();
  const toggle = document.createElement("button");
  toggle.className = "toggle";
  toggle.textContent = "Fantasy Picker";
  const panel = document.createElement("section");
  panel.hidden = true;
  panel.className = "panel";
  shadow.append(style, toggle, panel);
  document.body.append(host);

  let board = emptyBoard();
  let selectedPlayer: PlayerIndexPlayer | null = null;
  let suggestionPending = false;
  const render = (): void => {
    panel.replaceChildren();
    const heading = element(document, "h2", "Fantasy Picker");
    const description = element(
      document,
      "p",
      "Maintain this board manually. ESPN page data is never read.",
    );
    const slot = document.createElement("select");
    slot.setAttribute("aria-label", "My draft slot");
    slot.append(option(document, "My draft slot", ""));
    for (let value = 1; value <= 12; value += 1) {
      slot.append(
        option(
          document,
          `Draft slot ${value}`,
          String(value),
          board.draft_slot === value,
        ),
      );
    }
    slot.addEventListener("change", () => {
      const value = slot.value ? Number(slot.value) : null;
      void updateBoard(setDraftSlot(board, value));
    });

    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = "Search prepared players";
    search.setAttribute("aria-label", "Search prepared players");
    const results = document.createElement("select");
    results.setAttribute("aria-label", "Player search results");
    results.append(option(document, "Select a player", ""));
    const refreshResults = (): void => {
      selectedPlayer = null;
      results.replaceChildren(option(document, "Select a player", ""));
      for (const player of searchPlayers(index, search.value).slice(0, 20)) {
        results.append(
          option(document, player.display_name, player.canonical_player_id),
        );
      }
    };
    search.addEventListener("input", refreshResults);
    results.addEventListener("change", () => {
      selectedPlayer =
        index.players.find(
          (player) => player.canonical_player_id === results.value,
        ) ?? null;
    });
    const rosterButton = document.createElement("button");
    rosterButton.textContent = "Add to my roster";
    const takenButton = document.createElement("button");
    takenButton.textContent = "Add taken player";
    const add = (destination: "roster" | "taken"): void => {
      if (!selectedPlayer) {
        setStatus("Select a prepared player first.", "error");
        return;
      }
      try {
        void updateBoard(
          addPlayer(
            board,
            selectedPlayer.canonical_player_id,
            destination,
            index,
          ),
        );
        search.value = "";
        refreshResults();
      } catch (error) {
        setStatus(
          error instanceof Error
            ? error.message
            : "Unable to update the board.",
          "error",
        );
      }
    };
    rosterButton.addEventListener("click", () => add("roster"));
    takenButton.addEventListener("click", () => add("taken"));

    const status = element(document, "p", "", "status");
    const recommendations = document.createElement("div");
    const setStatus = (message: string, level: "error" | "info"): void => {
      status.textContent = message;
      status.dataset.level = level;
    };
    const list = (title: string, ids: string[]): HTMLElement => {
      const container = document.createElement("section");
      container.append(element(document, "h3", `${title} (${ids.length})`));
      const items = document.createElement("ul");
      for (const playerId of ids) {
        const player = index.players.find(
          (entry) => entry.canonical_player_id === playerId,
        );
        if (!player) {
          continue;
        }
        const item = document.createElement("li");
        item.append(document.createTextNode(player.display_name));
        const remove = document.createElement("button");
        remove.textContent = "Remove";
        remove.addEventListener(
          "click",
          () => void updateBoard(removePlayer(board, playerId)),
        );
        item.append(remove);
        items.append(item);
      }
      container.append(items);
      return container;
    };
    const suggest = document.createElement("button");
    suggest.textContent = "Suggest picks";
    suggest.disabled = suggestionPending;
    const retry = document.createElement("button");
    retry.textContent = "Retry suggestions";
    retry.hidden = true;
    const requestSuggestions = (): void => {
      if (suggestionPending) {
        return;
      }
      suggestionPending = true;
      suggest.disabled = true;
      retry.hidden = true;
      setStatus("Loading recommendations…", "info");
      void callbacks
        .suggest(board)
        .then(({ response, freshness }) => {
          const freshnessMessage = freshnessStatus(freshness);
          setStatus(
            `Updated in ${response.latency_ms} ms.${freshnessMessage ? ` ${freshnessMessage}` : ""}`,
            "info",
          );
          renderRecommendations(document, recommendations, response, freshness);
        })
        .catch((error: unknown) => {
          setStatus(
            error instanceof Error
              ? error.message
              : "Unable to request suggestions.",
            "error",
          );
          retry.hidden = false;
        })
        .finally(() => {
          suggestionPending = false;
          suggest.disabled = false;
        });
    };
    suggest.addEventListener("click", requestSuggestions);
    retry.addEventListener("click", requestSuggestions);
    const clear = document.createElement("button");
    clear.textContent = "Clear manual board";
    clear.addEventListener("click", () => void updateBoard(emptyBoard()));

    panel.append(
      heading,
      description,
      slot,
      search,
      results,
      rosterButton,
      takenButton,
      list("My roster", board.roster_ids),
      list("Taken players", board.taken_ids),
      suggest,
      retry,
      clear,
      status,
      recommendations,
    );

    async function updateBoard(next: ManualBoardState): Promise<void> {
      board = next;
      await callbacks.saveBoard(board);
      render();
    }
  };
  toggle.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
  });
  void callbacks.loadBoard().then((saved) => {
    board = saved;
    render();
  });
  return { host, destroy: () => host.remove() };
}

function element(
  document: Document,
  tag: string,
  text: string,
  className?: string,
): HTMLElement {
  const result = document.createElement(tag);
  result.textContent = text;
  if (className) {
    result.className = className;
  }
  return result;
}

function option(
  document: Document,
  text: string,
  value: string,
  selected = false,
): HTMLOptionElement {
  const result = document.createElement("option");
  result.textContent = text;
  result.value = value;
  result.selected = selected;
  return result;
}

export function renderRecommendations(
  document: Document,
  container: HTMLDivElement,
  response: RecommendationResponse,
  freshness?: Freshness,
): void {
  container.replaceChildren();
  container.append(
    element(document, "h3", `Recommendations · ${response.data_version}`),
  );
  for (const recommendation of response.recommendations) {
    container.append(
      element(
        document,
        "p",
        `${recommendation.rank}. ${recommendation.display_name} — ${recommendation.score}/10 · ${recommendation.strong_categories.join(", ")} · gain ${recommendation.category_win_gain} · injury -${recommendation.injury_penalty_pct}%`,
      ),
    );
  }
  for (const warning of response.warnings) {
    container.append(element(document, "p", `Warning: ${warning}`, "warning"));
  }
  const freshnessMessage = freshnessStatus(freshness);
  if (freshnessMessage) {
    container.append(element(document, "p", freshnessMessage, "warning"));
  }
}

function freshnessStatus(freshness: Freshness | undefined): string | null {
  if (!freshness || freshness.status === "fresh") {
    return null;
  }
  if (freshness.status === "stale") {
    return `Warning: prepared data is ${freshness.ageDays} days old; rebuild artifacts before the draft.`;
  }
  return `Warning: ${freshness.message}`;
}

function styles(): string {
  return `
    :host { all: initial; }
    .toggle { position: fixed; right: 16px; bottom: 16px; z-index: 2147483647; }
    .panel { position: fixed; right: 16px; bottom: 56px; z-index: 2147483647; width: 360px; max-height: 75vh; overflow: auto; padding: 16px; background: #111827; color: #f9fafb; border-radius: 8px; font: 14px system-ui, sans-serif; box-shadow: 0 8px 30px #0008; }
    button, input, select { margin: 4px; font: inherit; }
    input, select { max-width: 100%; }
    ul { padding-left: 20px; }
    li { margin: 4px 0; }
    .status[data-level="error"] { color: #fca5a5; }
    .warning { color: #fde68a; }
  `;
}
