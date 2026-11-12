"use strict";

(() => {
  // Elementos da tela e códigos recebidos do back-end.
  const root = document.getElementById("main");
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const input = $("player-search"),
    submit = $("guess-submit"),
    list = $("suggestions");
  const feedback = $("search-feedback"),
    message = $("game-message");
  const statuses = {
    correct: "Correto",
    partial: "Em comum",
    incorrect: "Diferente"
  };
  const career = {
    active: "Ativo",
    inactive: "Inativo",
    retired: "Aposentado",
    unknown: "Desconhecido"
  };
  const directions = {
    up: ["↑", "O ano secreto é posterior"],
    down: ["↓", "O ano secreto é anterior"],
    ongoing: ["∞", "O período secreto segue em andamento"],
    ended: ["■", "O período secreto tem fim definido"]
  };
  const regionNames = typeof Intl.DisplayNames === "function" ? new Intl.DisplayNames(["pt-BR"], {
    type: "region"
  }) : null;

  // Estado local da interface: desafio, seleção, envio e requisições em andamento.
  let challenge = null,
    selected = null,
    sending = false,
    ready = false;
  let options = [],
    active = -1,
    searchVersion = 0,
    searchController = null,
    debounce = null;
  let loadVersion = 0,
    retryTimer = null,
    retryDelay = 5000,
    clockOffset = 0,
    rolloverRequested = null;
  let hintData = {},
    hintGame = null;
  const revealedHints = new Set();

  // Montagem segura dos elementos: os dados externos entram como texto.
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function accessible(text) {
    return element("span", "sr-only", text);
  }

  function imageURL(value) {
    if (!value) return root.dataset.fallback;
    try {
      const url = new URL(value, window.location.origin);
      return ["https:", "http:"].includes(url.protocol) ? url.href : root.dataset.fallback;
    } catch {
      return root.dataset.fallback;
    }
  }

  function identity(player) {
    const group = element("div", "identity"),
      photo = element("img", "portrait");
    photo.alt = ""; // O nick ao lado já identifica o jogador.
    photo.width = 42;
    photo.height = 48;
    photo.referrerPolicy = "no-referrer";
    photo.addEventListener("error", () => {
      photo.src = root.dataset.fallback;
    }, {
      once: true
    });
    photo.src = imageURL(player.photo_url);
    const text = element("div");
    const shortName = (player.display_name || player.name || "").trim().split(/\s+/).slice(0, 2)
      .join(" ");
    text.append(element("strong", null, player.nick), element("small", null, shortName));
    group.append(photo, text);
    return group;
  }

  function teamIdentity(player) {
    const group = element("div", "team-identity");
    if (player.team_logo_url) {
      const logo = element("img", "team-logo");
      logo.alt = "";
      logo.width = 26;
      logo.height = 26;
      logo.addEventListener("error", () => logo.remove(), { once: true });
      logo.src = imageURL(player.team_logo_url);
      group.append(logo);
    }
    group.append(element("span", null, player.current_team || "No team"));
    return group;
  }

  function resultCell(result, content, className = "") {
    const cell = element("td", `${className} ${statuses[result] ? result : ""}`.trim());
    cell.append(content, accessible(`. ${statuses[result] || ""}.`));
    return cell;
  }

  function countries(codes) {
    const container = element("div", "nationalities");
    for (const code of codes) {
      let name = code;
      try {
        name = regionNames ? regionNames.of(code) : code;
      } catch {
        /* Código preservado. */
      }
      const item = element("span", "country");
      const flag = /^[A-Z]{2}$/.test(code) ? String.fromCodePoint(...Array.from(code, c =>
        127397 + c.charCodeAt(0))) : "";
      const symbol = element("span", null, flag);
      symbol.setAttribute("aria-hidden", "true");
      item.append(symbol, document.createTextNode(` ${name}`));
      container.append(item);
    }
    return container;
  }

  function roles(values) {
    const container = element("div", "role-list");
    for (const value of values) {
      if (value === "rifle") {
        const icon = element("img", "role-icon");
        icon.src = root.dataset.rifleIcon;
        icon.alt = "Rifle";
        icon.width = 20;
        icon.height = 20;
        container.append(icon);
      } else {
        const name = value === "awp" ? "AWP" : "IGL";
        const icon = element("span", "role-emoji", value === "awp" ? "🎯" : "🧠");
        icon.setAttribute("role", "img");
        icon.setAttribute("aria-label", name);
        container.append(icon);
      }
    }
    return container;
  }

  function activity(player, comparison) {
    // Só apresenta o período escolhido e as direções do servidor; não compara anos.
    const parts = player.years_active.split(" – ");
    const cell = element("td", "activity"),
      period = element("div", "activity-period");
    ["start", "end"].forEach((key, index) => {
      const result = comparison[key];
      const segment = element("span",
        `activity-year ${statuses[result.status] ? result.status : ""}`);
      segment.append(element("span", null, parts[index]));
      const [symbol, description] = result.status === "correct" ? ["✓", "Correto"] : (
        directions[result.direction] || ["", "Diferente"]);
      const indicator = element("span", "activity-indicator", symbol);
      indicator.setAttribute("aria-hidden", "true");
      segment.append(indicator, accessible(
        `${index === 0 ? "Início" : "Fim"}: ${description}.`));
      if (index) period.append(element("span", null, "–"));
      period.append(segment);
    });
    cell.append(period);
    return cell;
  }

  // A tabela apenas apresenta as comparações já calculadas pelo servidor.
  function row(guess) {
    const player = guess.player,
      comparison = guess.comparison,
      tr = element("tr");
    tr.dataset.number = guess.number;
    tr.append(
      resultCell(comparison.player, identity(player), "player"),
      resultCell(comparison.nationalities, countries(player.nationalities)),
      resultCell(comparison.career_status, element("span", null, career[player.career_status] ||
        player.career_status)),
      resultCell(comparison.current_team, teamIdentity(player)),
      resultCell(comparison.roles, roles(player.roles)),
      resultCell(comparison.is_major_winner, element("span", null, player.is_major_winner ?
        "🏆 Sim" : "Não")),
      activity(player, comparison.activity)
    );
    tr.firstElementChild.prepend(accessible(`Tentativa ${guess.number}. `));
    return tr;
  }

  function renderGuesses(guesses) {
    $("guesses").replaceChildren(...[...guesses].sort((a, b) => b.number - a.number).map(row));
    $("empty-board").hidden = guesses.length > 0;
  }

  function setControls() {
    input.disabled = !ready || sending || challenge?.state === "completed";
    submit.disabled = input.disabled || !selected;
    $("guess-form").setAttribute("aria-busy", String(sending));
    submit.textContent = sending ? "Enviando…" : "Enviar ↵";
  }

  function closeSuggestions() {
    list.hidden = true;
    active = -1;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  // Cancela a busca anterior e invalida respostas atrasadas.
  function cancelSearch() {
    clearTimeout(debounce);
    searchVersion += 1;
    searchController?.abort();
    options = [];
    closeSuggestions();
    list.replaceChildren();
  }

  function clearSelection() {
    selected = null;
    cancelSearch();
    setControls();
  }

  function choose(index) {
    const player = options[index];
    if (!player) return;
    selected = player;
    input.value = player.nick;
    cancelSearch();
    feedback.textContent = `${player.nick} selecionado. Envie sua tentativa.`;
    setControls();
    input.focus();
  }

  function highlight(index) {
    active = index;
    Array.from(list.children).forEach((node, i) => node.setAttribute("aria-selected", String(i ===
      index)));
    input.setAttribute("aria-activedescendant", `suggestion-${index}`);
    list.children[index]?.scrollIntoView({
      block: "nearest"
    });
  }

  // O cookie guarda o progresso; o lock coordena requisições entre abas do navegador.
  async function api(url, init = {}) {
    const controller = new AbortController();
    const cancel = () => controller.abort();
    if (init.signal?.aborted) cancel();
    else init.signal?.addEventListener("abort", cancel, {
      once: true
    });
    const timeout = setTimeout(cancel, 15000);
    const perform = async () => {
      const response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        ...init,
        signal: controller.signal
      });
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.error?.message ||
          "Não foi possível concluir. Tente novamente.");
        error.code = data.error?.code;
        error.status = response.status;
        throw error;
      }
      return {
        data,
        response
      };
    };

    try {
      if (navigator.locks) {
        return await navigator.locks.request(
          "csguess-classic-api",
          { signal: controller.signal },
          perform
        );
      }
      return await perform();
    } finally {
      clearTimeout(timeout);
      init.signal?.removeEventListener("abort", cancel);
    }
  }

  async function search(query, version) {
    const controller = new AbortController();
    searchController = controller;
    try {
      const url = new URL(root.dataset.searchUrl, window.location.origin);
      url.searchParams.set("q", query);
      const {
        data
      } = await api(url, {
        signal: controller.signal
      });
      if (version !== searchVersion || !ready || sending) return;
      options = data.players.slice(0, 10);
      list.replaceChildren();
      options.forEach((player, index) => {
        const option = element("li");
        option.id = `suggestion-${index}`;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        option.append(identity(player));
        option.addEventListener("mousedown", event => event.preventDefault());
        option.addEventListener("click", () => choose(index));
        list.append(option);
      });
      list.hidden = options.length === 0;
      input.setAttribute("aria-expanded", String(options.length > 0));
      feedback.textContent = options.length ?
        `${options.length} sugestão(ões). Use as setas e Enter para selecionar.` :
        "Nenhum jogador encontrado.";
    } catch (error) {
      if (version !== searchVersion) return;
      closeSuggestions();
      feedback.textContent = error.status ? error.message :
        "Falha ao buscar jogadores. Digite novamente para tentar.";
      if (error.code === "challenge_unavailable") {
        ready = false;
        setControls();
        scheduleRetry();
      }
    }
  }

  // Digitar invalida o jogador selecionado; a busca espera 300 ms.
  input.addEventListener("input", () => {
    clearSelection();
    const query = input.value.trim();
    if (query.length < 2) {
      feedback.textContent = "Digite pelo menos dois caracteres.";
      return;
    }
    feedback.textContent = "Buscando jogadores…";
    const version = searchVersion;
    debounce = setTimeout(() => search(query, version), 300);
  });
  input.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      cancelSearch();
      feedback.textContent = "";
      return;
    }
    if (list.hidden || !options.length) return;
    if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      highlight(event.key === "ArrowDown" ? (active + 1) % options.length : (active <= 0 ?
        options.length - 1 : active - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(active < 0 ? 0 : active);
    }
  });
  document.addEventListener("click", event => {
    if (!event.target.closest(".searchblock")) closeSuggestions();
  });
  input.addEventListener("blur", () => {
    setTimeout(() => {
      if (!$("guess-form").contains(document.activeElement)) closeSuggestions();
    }, 150);
  });

  function showVictory(summary) {
    $("victory").hidden = !summary;
    if (summary) $("victory-summary").textContent =
      `Você acertou ${summary.player.nick} em ${summary.attempts} ${summary.attempts === 1 ? "tentativa" : "tentativas"}. Volte no próximo desafio!`;
  }

  // O servidor libera as dicas; o clique decide quando mostrá-las na tela.
  function showHints(hints = {}, game = null) {
    if (game?.challenge_id !== hintGame?.challenge_id) revealedHints.clear();
    hintData = hints;
    hintGame = game;
    const playing = game?.state === "in_progress";
    $("game-hints").hidden = !playing;

    for (const [key, field, threshold] of [
      ["nationality", "nationalities", 10],
      ["team", "current_team", 15]
    ]) {
      const unlocked = playing && Object.hasOwn(hints, field);
      const revealed = unlocked && revealedHints.has(key);
      const button = $(`${key}-hint-button`);
      const remaining = Math.max(0, threshold - (game?.guesses.length || 0));
      button.disabled = !unlocked;
      button.setAttribute("aria-expanded", String(revealed));
      $(`${key}-hint-status`).textContent = unlocked
        ? (revealed ? "Clique para ocultar" : "Clique para revelar")
        : `Mais ${remaining} ${remaining === 1 ? "tentativa" : "tentativas"} para desbloquear`;
      $(`${key}-hint`).hidden = !revealed;
    }

    $("nationality-hint-value").replaceChildren(...(playing && revealedHints.has("nationality") && hints.nationalities
      ? [countries(hints.nationalities)] : []));
    $("team-hint-value").textContent = playing && revealedHints.has("team") ? (hints.current_team || "") : "";
  }

  for (const key of ["nationality", "team"]) {
    $(`${key}-hint-button`).addEventListener("click", () => {
      if (revealedHints.has(key)) revealedHints.delete(key);
      else revealedHints.add(key);
      showHints(hintData, hintGame);
    });
  }

  function scheduleRetry() {
    clearTimeout(retryTimer);
    retryTimer = setTimeout(() => loadState(), retryDelay);
    retryDelay = Math.min(retryDelay * 2, 60000);
  }

  // Recupera o desafio e reconstrói as tentativas do cookie deste navegador.
  async function loadState(notice = "") {
    const version = ++loadVersion;
    clearTimeout(retryTimer);
    ready = false;
    clearSelection();
    message.classList.remove("sr-only");
    message.textContent = notice || "Carregando o desafio…";
    const started = Date.now();
    try {
      const {
        data,
        response
      } = await api(root.dataset.stateUrl);
      if (version !== loadVersion) return;
      const serverTime = Date.parse(response.headers.get("Date"));
      if (Number.isFinite(serverTime)) clockOffset = serverTime - (started + Date.now()) / 2;
      challenge = data;
      ready = true;
      retryDelay = 5000;
      input.value = "";
      feedback.textContent = "";
      $("challenge-label").textContent =
        `DESAFIO DIÁRIO · ${data.challenge_date.split("-").reverse().join("/")}`;
      renderGuesses(data.guesses);
      showVictory(data.victory);
      showHints(data.hints, data);
      message.textContent = notice || "";
      setControls();
      tick();
      if (Date.parse(data.next_rollover) <= Date.now() + clockOffset) scheduleRetry();
    } catch (error) {
      if (version !== loadVersion) return;
      ready = false;
      setControls();
      message.textContent =
        `${error.status ? error.message : "Não foi possível carregar o desafio. Verifique sua conexão."} Tentaremos novamente em instantes.`;
      scheduleRetry();
    }
  }

  // Envia o ID selecionado e a data do desafio, mantendo a proteção CSRF.
  $("guess-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (!selected || !ready || sending || challenge?.state === "completed") return;
    const player = selected,
      currentDate = challenge.challenge_date;
    const version = loadVersion;
    sending = true;
    cancelSearch();
    setControls();
    message.classList.remove("sr-only");
    message.textContent = "";
    try {
      const csrf = $("guess-form").querySelector("[name=csrfmiddlewaretoken]").value;
      const {
        data
      } = await api(root.dataset.guessUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf
        },
        body: JSON.stringify({
          player_id: player.id,
          challenge_date: currentDate
        })
      });
      if (version !== loadVersion) return;
      challenge.guesses.push(data);
      challenge.state = data.state;
      renderGuesses(challenge.guesses);
      showVictory(data.victory);
      showHints(data.hints, challenge);
      input.value = "";
      selected = null;
      feedback.textContent = "";
      await loadState();
      progressChannel?.postMessage("updated");
      message.classList.add("sr-only");
      message.textContent = data.correct ? "Partida concluída!" :
        `Tentativa ${data.number} registrada.`;
    } catch (error) {
      if (version !== loadVersion) return;
      if (["challenge_changed", "session_required", "match_completed", "duplicate_guess"]
        .includes(error.code)) {
        if (error.code === "challenge_changed") {
          renderGuesses([]);
          showVictory(null);
          showHints();
        }
        await loadState(error.message);
      } else if (!error.status || error.status >= 500) {
        // Se o cookie já chegou antes da falha, recupera o progresso antes de reenviar.
        await loadState("Conferindo suas tentativas após uma falha de conexão.");
      } else {
        message.textContent = error.message;
        if (error.code === "csrf_failed") message.textContent += " Recarregue esta página.";
      }
    } finally {
      sending = false;
      setControls();
      if (!input.disabled) input.focus();
    }
  });


  // O horário de virada vem da API; o navegador apenas atualiza o contador.
  function tick() {
    if (!challenge) return;
    const milliseconds = Date.parse(challenge.next_rollover) - Date.now() - clockOffset;
    const seconds = Math.max(0, Math.ceil(milliseconds / 1000));
    const h = Math.floor(seconds / 3600),
      m = Math.floor(seconds % 3600 / 60),
      s = seconds % 60;
    $("countdown").textContent = [h, m, s].map(value => String(value).padStart(2, "0")).join(":");
    if (seconds === 0 && rolloverRequested !== challenge.next_rollover) {
      rolloverRequested = challenge.next_rollover;
      ready = false;
      clearSelection();
      renderGuesses([]);
      showVictory(null);
      showHints();
      loadState("Um novo dia começou. Carregando o desafio…");
    }
  }

  // Outras abas do mesmo navegador atualizam a tela após uma tentativa.
  const progressChannel = typeof BroadcastChannel === "function"
    ? new BroadcastChannel("csguess-classic-progress")
    : null;
  progressChannel?.addEventListener("message", () => loadState());

  // Ajuda e inicialização da tela.
  const dialog = $("help-dialog");
  $("help-open").addEventListener("click", () => dialog.showModal());
  $("help-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", event => {
    if (event.target === dialog) {
      const bounds = dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY <
        bounds.top || event.clientY > bounds.bottom) dialog.close();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) tick();
  });
  window.addEventListener("online", () => {
    if (!ready) loadState();
  });
  setInterval(tick, 1000);
  loadState();
})();
