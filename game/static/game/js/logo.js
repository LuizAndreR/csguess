"use strict";

(() => {
  const root = document.getElementById("main");
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const input = $("team-search"),
    submit = $("guess-submit"),
    list = $("suggestions"),
    feedback = $("search-feedback"),
    message = $("game-message"),
    image = $("logo-image");

  let challenge = null,
    selected = null,
    sending = false,
    ready = false,
    options = [],
    active = -1,
    searchVersion = 0,
    searchController = null,
    debounce = null,
    loadVersion = 0,
    retryTimer = null,
    retryDelay = 5000,
    clockOffset = 0,
    rolloverRequested = null;

  // Os nomes entram sempre como texto, nunca como HTML.
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function api(url, init = {}) {
    const controller = new AbortController();
    const cancel = () => controller.abort();
    if (init.signal?.aborted) cancel();
    else init.signal?.addEventListener("abort", cancel, { once: true });
    const timeout = setTimeout(cancel, 15000);
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        ...init,
        signal: controller.signal
      });
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.error?.message || "Não foi possível concluir. Tente novamente.");
        error.code = data.error?.code;
        error.status = response.status;
        throw error;
      }
      return { data, response };
    } finally {
      clearTimeout(timeout);
      init.signal?.removeEventListener("abort", cancel);
    }
  }

  // Tentativas, da mais recente para a mais antiga: errada em vermelho, certa em verde.
  function renderGuesses(guesses) {
    const items = [...guesses].sort((a, b) => b.number - a.number).map(guess => {
      const item = element("li", guess.correct ? "correct" : "incorrect");
      item.value = guess.number;
      const verdict = guess.correct ? "Correta" : "Errada";
      item.append(
        element("span", "number", `#${guess.number}`),
        element("strong", null, guess.team.name),
        element("span", "verdict", verdict)
      );
      return item;
    });
    $("guesses").replaceChildren(...items);
    $("empty-board").hidden = guesses.length > 0;
  }

  function showImage(data) {
    // A URL muda a cada nível, para o navegador não reaproveitar a versão mais embaçada.
    const url = new URL(data.image_url, window.location.origin).href;
    if (image.src !== url) image.src = url;
    image.hidden = false;
    $("logo-loading").hidden = true;
    const solved = data.state === "completed" || data.victory;
    image.alt = solved && data.victory ? `Logo da equipe ${data.victory.team.name}` :
      "Logo da equipe do dia, desfocado";
    const note = $("blur-note");
    if (solved) note.textContent = "Logo revelado.";
    else if (data.attempts_to_next_level === null) note.textContent = "Imagem nítida.";
    else note.textContent =
      `Mais nítida em ${data.attempts_to_next_level} ${data.attempts_to_next_level === 1 ? "tentativa" : "tentativas"}.`;
  }
  image.addEventListener("error", () => {
    image.hidden = true;
    $("logo-loading").hidden = false;
    $("logo-loading").textContent = "Não foi possível carregar a imagem. Recarregue a página.";
  });

  function showVictory(summary) {
    $("victory").hidden = !summary;
    if (summary) $("victory-summary").textContent =
      `Você acertou: ${summary.team.name}, em ${summary.attempts} ${summary.attempts === 1 ? "tentativa" : "tentativas"}. Volte no próximo desafio!`;
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
    const team = options[index];
    if (!team) return;
    selected = team;
    input.value = team.name;
    cancelSearch();
    feedback.textContent = `${team.name} selecionada. Envie sua tentativa.`;
    setControls();
    input.focus();
  }

  function highlight(index) {
    active = index;
    Array.from(list.children).forEach((node, i) => node.setAttribute("aria-selected", String(i === index)));
    input.setAttribute("aria-activedescendant", `suggestion-${index}`);
    list.children[index]?.scrollIntoView({ block: "nearest" });
  }

  function scheduleRetry() {
    clearTimeout(retryTimer);
    retryTimer = setTimeout(() => loadState(), retryDelay);
    retryDelay = Math.min(retryDelay * 2, 60000);
  }

  async function search(query, version) {
    const controller = new AbortController();
    searchController = controller;
    try {
      const url = new URL(root.dataset.searchUrl, window.location.origin);
      url.searchParams.set("q", query);
      const { data } = await api(url, { signal: controller.signal });
      if (version !== searchVersion || !ready || sending) return;
      options = data.teams.slice(0, 10);
      list.replaceChildren();
      options.forEach((team, index) => {
        const option = element("li", null, team.name);
        option.id = `suggestion-${index}`;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        option.addEventListener("mousedown", event => event.preventDefault());
        option.addEventListener("click", () => choose(index));
        list.append(option);
      });
      list.hidden = options.length === 0;
      input.setAttribute("aria-expanded", String(options.length > 0));
      feedback.textContent = options.length ?
        `${options.length} sugestão(ões). Use as setas e Enter para selecionar.` :
        "Nenhuma equipe encontrada.";
    } catch (error) {
      if (version !== searchVersion) return;
      closeSuggestions();
      feedback.textContent = error.status ? error.message :
        "Falha ao buscar equipes. Digite novamente para tentar.";
      if (error.code === "challenge_unavailable") {
        ready = false;
        setControls();
        scheduleRetry();
      }
    }
  }

  input.addEventListener("input", () => {
    clearSelection();
    const query = input.value.trim();
    if (query.length < 2) {
      feedback.textContent = "Digite pelo menos dois caracteres.";
      return;
    }
    feedback.textContent = "Buscando equipes…";
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
      highlight(event.key === "ArrowDown" ? (active + 1) % options.length :
        (active <= 0 ? options.length - 1 : active - 1));
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

  // Recupera o desafio e reconstrói as tentativas a partir do cookie deste navegador.
  async function loadState(notice = "") {
    const version = ++loadVersion;
    clearTimeout(retryTimer);
    ready = false;
    clearSelection();
    message.classList.remove("sr-only");
    message.textContent = notice || "Carregando o desafio…";
    const started = Date.now();
    try {
      const { data, response } = await api(root.dataset.stateUrl);
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
      showImage(data);
      showVictory(data.victory);
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

  $("guess-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (!selected || !ready || sending || challenge?.state === "completed") return;
    const team = selected,
      currentDate = challenge.challenge_date,
      version = loadVersion;
    sending = true;
    cancelSearch();
    setControls();
    message.classList.remove("sr-only");
    message.textContent = "";
    try {
      const csrf = $("guess-form").querySelector("[name=csrfmiddlewaretoken]").value;
      const { data } = await api(root.dataset.guessUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ team_id: team.id, challenge_date: currentDate })
      });
      if (version !== loadVersion) return;
      challenge.guesses.push(data);
      challenge.state = data.state;
      renderGuesses(challenge.guesses);
      showImage(data);
      showVictory(data.victory);
      input.value = "";
      selected = null;
      feedback.textContent = "";
      message.classList.add("sr-only");
      message.textContent = data.correct ? "Partida concluída!" : `Tentativa ${data.number} registrada.`;
    } catch (error) {
      if (version !== loadVersion) return;
      if (["challenge_changed", "session_required", "match_completed", "duplicate_guess"].includes(error.code)) {
        if (error.code === "challenge_changed") renderGuesses([]);
        await loadState(error.message);
      } else if (!error.status || error.status >= 500) {
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

  // O horário de virada vem da API; o navegador só atualiza o contador.
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
      loadState("Um novo dia começou. Carregando o desafio…");
    }
  }

  const dialog = $("help-dialog");
  $("help-open").addEventListener("click", () => dialog.showModal());
  $("help-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", event => {
    if (event.target === dialog) {
      const b = dialog.getBoundingClientRect();
      if (event.clientX < b.left || event.clientX > b.right || event.clientY < b.top ||
        event.clientY > b.bottom) dialog.close();
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
