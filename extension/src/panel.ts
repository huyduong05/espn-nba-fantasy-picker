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
  const launcher = button(document, "Fantasy Picker", "launcher");
  launcher.setAttribute("aria-label", "Open Fantasy Picker");
  const drawer = document.createElement("aside");
  drawer.className = "drawer";
  drawer.hidden = true;
  shadow.append(style, launcher, drawer);
  document.body.append(host);

  let board = emptyBoard();
  let selectedPlayer: PlayerIndexPlayer | null = null;
  let searchQuery = "";
  let suggestionPending = false;
  let initializationError: string | null = null;
  let focusSearchOnRender = false;

  const render = (): void => {
    drawer.replaceChildren();
    const header = document.createElement("header");
    header.className = "drawer-header";
    const titleGroup = document.createElement("div");
    titleGroup.append(
      element(document, "span", "FANTASY TOOL", "eyebrow"),
      element(document, "h2", "Fantasy Picker"),
    );
    const close = button(document, "×", "icon-button");
    close.setAttribute("aria-label", "Close Fantasy Picker");
    close.addEventListener("click", () => closeDrawer());
    header.append(titleGroup, close);

    const intro = element(
      document,
      "p",
      "Build your board manually, then get a fresh recommendation set whenever you need it.",
      "intro",
    );

    const searchSection = document.createElement("section");
    searchSection.className = "search-section";
    searchSection.append(
      element(document, "label", "Find a prepared player", "section-label"),
    );
    const search = document.createElement("input");
    search.type = "search";
    search.value = searchQuery;
    search.placeholder = "Search by name or alias…";
    search.setAttribute("aria-label", "Search prepared players");
    search.addEventListener("input", () => {
      searchQuery = search.value;
      selectedPlayer = null;
      renderSearchResults(results, selection, search.value);
    });
    searchSection.append(search);
    const results = document.createElement("div");
    results.className = "results";
    const selection = document.createElement("div");
    selection.className = "selection";
    searchSection.append(results, selection);

    const rosterSection = boardSection(document, "My roster", board.roster_ids);
    const takenSection = boardSection(
      document,
      "Taken players",
      board.taken_ids,
    );

    const suggestSection = document.createElement("section");
    suggestSection.className = "suggest-section";
    const suggest = button(document, "Suggest picks", "primary-button");
    suggest.disabled = suggestionPending;
    suggest.addEventListener("click", requestSuggestions);
    const clear = button(document, "Clear board", "text-button");
    clear.addEventListener("click", () => void updateBoard(emptyBoard()));
    suggestSection.append(suggest, clear);

    const status = element(document, "p", "", "status");
    const recommendations = document.createElement("div");
    recommendations.className = "recommendations";
    if (initializationError) {
      setStatus(status, initializationError, "error");
    }

    drawer.append(
      header,
      intro,
      searchSection,
      rosterSection,
      takenSection,
      suggestSection,
      status,
      recommendations,
    );
    renderSearchResults(results, selection, searchQuery);
    if (focusSearchOnRender) {
      focusSearchOnRender = false;
      search.focus();
    }

    function requestSuggestions(): void {
      if (suggestionPending) {
        return;
      }
      suggestionPending = true;
      suggest.disabled = true;
      setStatus(status, "Loading recommendations…", "info");
      void callbacks
        .suggest(board)
        .then(({ response, freshness }) => {
          const freshMessage = freshnessMessage(freshness);
          setStatus(
            status,
            `Updated in ${response.latency_ms} ms${freshMessage ? ` · ${freshMessage}` : ""}`,
            "info",
          );
          renderRecommendations(document, recommendations, response, freshness);
        })
        .catch((error: unknown) => {
          setStatus(
            status,
            error instanceof Error
              ? error.message
              : "Unable to request suggestions.",
            "error",
          );
        })
        .finally(() => {
          suggestionPending = false;
          suggest.disabled = false;
        });
    }

    function renderSearchResults(
      resultContainer: HTMLDivElement,
      selectionContainer: HTMLDivElement,
      query: string,
    ): void {
      resultContainer.replaceChildren();
      selectionContainer.replaceChildren();
      if (!query.trim()) {
        resultContainer.append(
          element(
            document,
            "p",
            "Start typing to see the best matches.",
            "empty-state",
          ),
        );
        return;
      }
      const matches = searchPlayers(index, query).slice(0, 5);
      if (!matches.length) {
        resultContainer.append(
          element(
            document,
            "p",
            "No prepared players match that search.",
            "empty-state",
          ),
        );
        return;
      }
      for (const player of matches) {
        const result = button(document, "", "result-card");
        result.setAttribute("aria-label", `Select ${player.display_name}`);
        result.setAttribute(
          "aria-pressed",
          selectedPlayer?.canonical_player_id === player.canonical_player_id
            ? "true"
            : "false",
        );
        result.append(
          element(document, "strong", player.display_name),
          element(
            document,
            "span",
            player.positions.join(" · "),
            "result-meta",
          ),
        );
        result.addEventListener("click", () => {
          selectedPlayer = player;
          renderSearchResults(resultContainer, selectionContainer, query);
        });
        resultContainer.append(result);
      }
      if (!selectedPlayer) {
        return;
      }
      const selected = selectedPlayer;
      const selectedCard = document.createElement("div");
      selectedCard.className = "selected-card";
      selectedCard.append(
        element(document, "span", "SELECTED PLAYER", "eyebrow"),
        element(document, "strong", selected.display_name),
      );
      const existingDestination = boardDestination(
        board,
        selected.canonical_player_id,
      );
      if (existingDestination) {
        selectedCard.append(
          element(
            document,
            "span",
            `Already added to ${existingDestination}.`,
            "result-meta",
          ),
        );
      } else {
        const actions = document.createElement("div");
        actions.className = "selection-actions";
        const rosterAction = button(document, "Add to roster", "small-primary");
        const takenAction = button(
          document,
          "Mark as taken",
          "small-secondary",
        );
        rosterAction.addEventListener(
          "click",
          () => void addSelected("roster"),
        );
        takenAction.addEventListener("click", () => void addSelected("taken"));
        actions.append(rosterAction, takenAction);
        selectedCard.append(actions);
      }
      selectionContainer.append(selectedCard);
    }

    async function addSelected(destination: "roster" | "taken"): Promise<void> {
      if (!selectedPlayer) {
        return;
      }
      try {
        const next = addPlayer(
          board,
          selectedPlayer.canonical_player_id,
          destination,
          index,
        );
        selectedPlayer = null;
        searchQuery = "";
        focusSearchOnRender = true;
        await updateBoard(next);
      } catch (error) {
        setStatus(
          status,
          error instanceof Error
            ? error.message
            : "Unable to update the board.",
          "error",
        );
      }
    }

    function boardSection(
      document: Document,
      title: string,
      ids: string[],
    ): HTMLDetailsElement {
      const section = document.createElement("details");
      section.className = "board-section";
      section.open = true;
      const summary = document.createElement("summary");
      summary.append(
        element(document, "span", title),
        element(document, "span", String(ids.length), "count-badge"),
      );
      section.append(summary);
      const list = document.createElement("div");
      list.className = "board-list";
      if (!ids.length) {
        list.append(
          element(document, "p", "Nothing recorded yet.", "empty-state"),
        );
      }
      for (const playerId of ids) {
        const player = index.players.find(
          (entry) => entry.canonical_player_id === playerId,
        );
        if (!player) {
          continue;
        }
        const row = document.createElement("div");
        row.className = "board-row";
        row.append(
          element(document, "span", player.display_name),
          element(
            document,
            "span",
            player.positions.join(" · "),
            "result-meta",
          ),
        );
        const remove = button(document, "Remove", "remove-button");
        remove.addEventListener(
          "click",
          () => void updateBoard(removePlayer(board, playerId)),
        );
        row.append(remove);
        list.append(row);
      }
      section.append(list);
      return section;
    }

    async function updateBoard(next: ManualBoardState): Promise<void> {
      try {
        await callbacks.saveBoard(next);
        board = next;
        render();
      } catch (error) {
        setStatus(
          status,
          error instanceof Error ? error.message : "Unable to save the board.",
          "error",
        );
      }
    }
  };

  const openDrawer = (): void => {
    drawer.hidden = false;
    launcher.hidden = true;
  };
  const closeDrawer = (): void => {
    drawer.hidden = true;
    launcher.hidden = false;
  };
  launcher.addEventListener("click", openDrawer);
  void callbacks
    .loadBoard()
    .then((saved) => {
      board = normalizeBoard(saved);
      render();
    })
    .catch((error: unknown) => {
      initializationError =
        error instanceof Error
          ? error.message
          : "The manual draft board could not be loaded.";
      render();
    });

  return { host, destroy: () => host.remove() };
}

function normalizeBoard(board: ManualBoardState): ManualBoardState {
  return { roster_ids: [...board.roster_ids], taken_ids: [...board.taken_ids] };
}

function boardDestination(
  board: ManualBoardState,
  playerId: string,
): "your roster" | "taken players" | null {
  if (board.roster_ids.includes(playerId)) {
    return "your roster";
  }
  if (board.taken_ids.includes(playerId)) {
    return "taken players";
  }
  return null;
}

function button(
  document: Document,
  text: string,
  className: string,
): HTMLButtonElement {
  const result = document.createElement("button");
  result.type = "button";
  result.textContent = text;
  result.className = className;
  return result;
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

export function renderRecommendations(
  document: Document,
  container: HTMLDivElement,
  response: RecommendationResponse,
  freshness?: Freshness,
): void {
  container.replaceChildren();
  container.append(
    element(document, "h3", "Top recommendations", "section-title"),
  );
  for (const recommendation of response.recommendations) {
    const card = document.createElement("article");
    card.className = "recommendation-card";
    const rank = element(document, "span", `#${recommendation.rank}`, "rank");
    const body = document.createElement("div");
    body.append(
      element(document, "strong", recommendation.display_name),
      element(
        document,
        "span",
        `${recommendation.positions.join(" · ")} · ${recommendation.strong_categories.join(", ") || "Balanced profile"}`,
        "result-meta",
      ),
    );
    const score = element(
      document,
      "strong",
      `${recommendation.score}/10`,
      "score",
    );
    card.append(rank, body, score);
    container.append(card);
  }
  for (const warning of response.warnings) {
    container.append(element(document, "p", `Warning: ${warning}`, "warning"));
  }
  const message = freshnessMessage(freshness);
  if (message) {
    container.append(element(document, "p", message, "warning"));
  }
}

function freshnessMessage(freshness: Freshness | undefined): string | null {
  if (!freshness || freshness.status === "fresh") {
    return null;
  }
  if (freshness.status === "stale") {
    return `Prepared data is ${freshness.ageDays} days old.`;
  }
  return freshness.message;
}

function setStatus(
  status: HTMLElement,
  message: string,
  level: "error" | "info",
): void {
  status.textContent = message;
  status.dataset.level = level;
}

function styles(): string {
  return `
    :host { all: initial; }
    .launcher, .drawer { color: #172033; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .launcher { position: fixed; right: 16px; bottom: 80px; z-index: 2147483647; border: 0; border-radius: 999px; padding: 12px 18px; background: #e87516; color: #fff; font-size: 13px; font-weight: 800; letter-spacing: .01em; box-shadow: 0 8px 24px #16203340; cursor: pointer; }
    .launcher:hover, .primary-button:hover, .small-primary:hover { background: #c95d08; }
    .drawer { position: fixed; top: 16px; right: 16px; bottom: 120px; z-index: 2147483647; width: min(390px, calc(100vw - 32px)); overflow-y: auto; background: #f8fafc; border: 1px solid #dbe3ef; border-radius: 18px; box-shadow: 0 18px 60px #1720333d; font-size: 14px; }
    .drawer-header { display: flex; align-items: center; justify-content: space-between; padding: 20px 20px 12px; background: linear-gradient(135deg, #102a56, #174a8d); color: #fff; }
    .drawer-header h2 { margin: 3px 0 0; font-size: 22px; letter-spacing: -.03em; }
    .eyebrow { display: block; color: #f6a35b; font-size: 10px; font-weight: 800; letter-spacing: .12em; }
    .intro, .search-section, .board-section, .suggest-section, .status, .recommendations { margin-left: 16px; margin-right: 16px; }
    .intro { margin-top: 14px; margin-bottom: 12px; color: #66748a; line-height: 1.45; }
    .icon-button { border: 0; background: transparent; color: #fff; font-size: 28px; line-height: 1; cursor: pointer; }
    .search-section { padding: 14px; background: #fff; border: 1px solid #e1e8f0; border-radius: 14px; }
    .section-label, .section-title { display: block; margin-bottom: 8px; color: #172033; font-size: 12px; font-weight: 800; letter-spacing: .02em; }
    input[type="search"] { box-sizing: border-box; width: 100%; margin: 0; padding: 11px 12px; border: 1px solid #cbd5e1; border-radius: 9px; background: #f8fafc; color: #172033; font: inherit; outline: none; }
    input[type="search"]:focus { border-color: #2574c7; box-shadow: 0 0 0 3px #2574c733; }
    .results { display: grid; gap: 6px; margin-top: 10px; }
    .result-card { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 9px 10px; border: 1px solid #e1e8f0; border-radius: 9px; background: #fff; color: #172033; text-align: left; cursor: pointer; }
    .result-card:hover, .result-card[aria-pressed="true"] { border-color: #2574c7; background: #eff6ff; }
    .result-card strong, .selected-card strong, .board-row span:first-child, .recommendation-card strong { display: block; }
    .result-meta { display: block; margin-top: 3px; color: #718096; font-size: 11px; }
    .selected-card { margin-top: 10px; padding: 11px; border-left: 3px solid #e87516; border-radius: 8px; background: #fff7ed; }
    .selection-actions, .suggest-section { display: flex; gap: 8px; align-items: center; }
    .selection-actions { margin-top: 9px; }
    .small-primary, .small-secondary, .primary-button, .text-button, .remove-button { border: 0; border-radius: 7px; padding: 8px 10px; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; }
    .small-primary, .primary-button { background: #2574c7; color: #fff; }
    .small-secondary { background: #dbeafe; color: #174a8d; }
    .board-section { margin-top: 10px; border: 1px solid #e1e8f0; border-radius: 12px; background: #fff; }
    .board-section summary { display: flex; justify-content: space-between; padding: 11px 13px; color: #172033; font-weight: 800; cursor: pointer; list-style: none; }
    .board-section summary::-webkit-details-marker { display: none; }
    .count-badge { min-width: 20px; padding: 2px 6px; border-radius: 999px; background: #e8eef7; color: #53657d; text-align: center; font-size: 11px; }
    .board-list { padding: 0 13px 10px; }
    .board-row { display: grid; grid-template-columns: 1fr auto auto; gap: 8px; align-items: center; padding: 8px 0; border-top: 1px solid #edf1f5; }
    .remove-button { padding: 4px 7px; background: #f1f5f9; color: #64748b; }
    .remove-button:hover { background: #fee2e2; color: #b91c1c; }
    .suggest-section { justify-content: space-between; margin-top: 14px; }
    .primary-button { flex: 1; padding: 11px 14px; }
    .text-button { background: transparent; color: #64748b; }
    .status { min-height: 18px; margin-top: 10px; margin-bottom: 0; color: #2574c7; font-size: 12px; }
    .status[data-level="error"], .warning { color: #b42318; }
    .recommendations { padding-bottom: 16px; }
    .recommendation-card { display: grid; grid-template-columns: 28px 1fr auto; gap: 9px; align-items: center; margin-bottom: 7px; padding: 10px; border: 1px solid #e1e8f0; border-radius: 10px; background: #fff; }
    .rank { color: #e87516; font-weight: 900; }
    .score { color: #174a8d; }
    .empty-state { margin: 9px 0 0; color: #8a97a9; font-size: 12px; }
    button:disabled { cursor: not-allowed; opacity: .55; }
  `;
}
