const app = document.querySelector("#app");

async function request(path, options) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) {
    let detail = "Não foi possível completar esta ação.";
    try { detail = (await response.json()).detail || detail; } catch { /* safe fallback */ }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

function header(project = null) {
  const element = document.createElement("header");
  element.className = "site-header";
  element.innerHTML = `
    <a class="brand" href="/"><span>100</span> discos africanos</a>
    <!-- <span class="local-mark">privado e local</span> -->
    ${project ? `<div class="progress-copy" aria-label="${project.progress} de ${project.total} discos revelados"><strong>${project.progress} / ${project.total}</strong><br />discos revelados<div class="progress-track"><span style="width: ${(project.progress / project.total) * 100}%"></span></div></div>` : ""}`;
  return element;
}

function setStatus(element, message, isError = false) {
  element.textContent = message;
  element.style.color = isError ? "#9b3328" : "";
}

function formatDate(value) {
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${value}T12:00:00Z`));
}

function appendAttribution(parent, source) {
  if (!source) return;
  const note = document.createElement("p");
  note.className = "attribution";
  note.append("Catálogo: ");
  const link = document.createElement("a");
  link.href = source.source_url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = source.attribution_text;
  note.append(link, ` · ${source.source_license}.`);
  parent.append(note);
}

async function renderHome() {
  document.body.classList.remove("today-page");
  document.title = "100 Discos Africanos";
  app.replaceChildren(header());
  const main = document.createElement("main");
  main.id = "content";
  main.className = "home-main";
  main.innerHTML = `
    <section class="hero">
      <h1>Explore os discos que atravessam a música <em>africana.</em></h1>
      <p class="hero-copy">Uma lista escolhida por leitores, 100 encontros e nenhum algoritmo disputando sua atenção. Crie uma lista e revele um disco por dia.</p>
      <form class="start-form" id="start-form">
        <input id="journey-name" name="name" maxlength="120" autocomplete="off" required placeholder="Dê um nome à sua lista" aria-label="Nome da lista" />
        <button class="button" type="submit">Começar agora</button>
      </form>
      <p class="form-note"><a href="/listas">Já tem uma lista?</a></p>
      <p class="status" id="home-status" role="status" aria-live="polite"></p>
    </section>
    <section class="how" aria-labelledby="how-title">
      <div class="section-heading">
        <h2 id="how-title">Como funciona</h2>
      </div>
      <div class="steps">
        <article class="step"><b>01</b><h3>Crie</h3><p>Escolha um nome memorável. Ele vira o endereço simples da sua lista.</p></article>
        <article class="step"><b>02</b><h3>Escute</h3><p>Revele um disco por dia, sem repetir e sem precisar escolher o próximo.</p></article>
        <article class="step"><b>03</b><h3>Registre</h3><p>Dê uma nota e escreva impressões privadas para acompanhar sua história.</p></article>
      </div>
    </section>`;
  app.append(main);

  const form = main.querySelector("#start-form");
  const status = main.querySelector("#home-status");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    setStatus(status, "Criando sua lista…");
    try {
      const journey = await request("/api/v1/journeys", {
        method: "POST",
        body: JSON.stringify({
          name: form.elements.name.value,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        }),
      });
      window.location.assign(`/${encodeURIComponent(journey.slug)}`);
    } catch (error) {
      setStatus(status, error.message, true);
      button.disabled = false;
    }
  });
}

function journeyFrame(project, section) {
  const fragment = document.createDocumentFragment();
  fragment.append(header(project));
  const main = document.createElement("main");
  main.id = "content";
  main.className = "journey-main";
  main.innerHTML = `
    <nav class="tabs" aria-label="Seções da jornada">
      <a class="tab" data-section="today">Hoje</a>
      <a class="tab" data-section="history">Histórico</a>
    </nav>
    <section class="view" id="view" aria-live="polite"><p>Carregando…</p></section>
    `;
  main.querySelectorAll(".tab").forEach((link) => {
    const target = link.dataset.section;
    link.href = target === "today"
      ? `/${encodeURIComponent(project.slug)}`
      : `/${encodeURIComponent(project.slug)}/${target}`;
    if (target === section) {
      link.classList.add("active");
      link.setAttribute("aria-current", "page");
    }
  });
  fragment.append(main);
  return { fragment, view: main.querySelector("#view") };
}

function fallbackCover(album, className = "cover") {
  const element = document.createElement("div");
  element.className = className;
  const label = document.createElement("small");
  label.textContent = "OkayAfrica Readers";
  const rank = document.createElement("strong");
  rank.textContent = String(album.rank).padStart(3, "0");
  element.append(label, rank);
  return element;
}

function cover(album) {
  if (!album.cover_url) return fallbackCover(album);
  const image = document.createElement("img");
  image.className = "cover cover-image";
  image.src = album.cover_url;
  image.alt = `Capa de ${album.title}, de ${album.artist_credit}`;
  image.addEventListener("error", () => image.replaceWith(fallbackCover(album)));
  return image;
}

function miniCover(album) {
  if (!album.cover_url) {
    const fallback = document.createElement("div");
    fallback.className = "mini-cover";
    fallback.textContent = album.rank;
    return fallback;
  }
  const image = document.createElement("img");
  image.className = "mini-cover mini-cover-image";
  image.src = album.cover_url;
  image.alt = "";
  image.addEventListener("error", () => image.replaceWith(miniCover({ ...album, cover_url: null })));
  return image;
}

function ratingForm(assignment, project, onSaved, compactSuccess = false) {
  const form = document.createElement("form");
  form.className = "rating-form";
  form.innerHTML = `
    <label>Sua nota</label>
    <div class="stars" role="group" aria-label="Nota de uma a cinco"></div>
    <label for="review">Impressões privadas</label>
    <textarea id="review" maxlength="4000" placeholder="O que ficou depois da escuta?"></textarea>
    <button class="button" type="submit">Salvar registro</button>
    <p class="status" role="status"></p>`;
  let score = assignment.rating?.score || 0;
  const stars = form.querySelector(".stars");
  const submitButton = form.querySelector("button[type=submit]");
  const resetSave = () => {
    if (!compactSuccess || !submitButton.classList.contains("save-confirmed")) return;
    submitButton.textContent = "Salvar registro";
    submitButton.classList.remove("save-confirmed");
    submitButton.removeAttribute("aria-label");
  };
  const updateStars = () => stars.querySelectorAll("button").forEach((button, index) => {
    button.classList.toggle("selected", index < score);
    button.setAttribute("aria-pressed", String(index + 1 === score));
  });
  for (let value = 1; value <= 5; value += 1) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = value;
    button.setAttribute("aria-label", `${value} de 5`);
    button.addEventListener("click", () => { score = value; updateStars(); resetSave(); });
    stars.append(button);
  }
  updateStars();
  const review = form.querySelector("textarea");
  review.value = assignment.rating?.review || "";
  review.addEventListener("input", resetSave);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = form.querySelector(".status");
    if (!score) return setStatus(status, "Escolha uma nota de 1 a 5.", true);
    try {
      await request(`/api/v1/journeys/${encodeURIComponent(project.slug)}/assignments/${assignment.id}/rating`, {
        method: "PUT",
        body: JSON.stringify({ score, review: form.querySelector("textarea").value }),
      });
      setStatus(status, "");
      if (compactSuccess) {
        submitButton.textContent = "✓";
        submitButton.classList.add("save-confirmed");
        submitButton.setAttribute("aria-label", "Registro salvo");
      }
      onSaved?.();
    } catch (error) { setStatus(status, error.message, true); }
  });
  return form;
}

function renderAlbum(parent, assignment, project) {
  const layout = document.createElement("div");
  layout.className = "today-layout";
  layout.append(cover(assignment.album));
  const detail = document.createElement("article");
  detail.className = "album-detail";
  detail.innerHTML = `<h2></h2><p class="artist"></p><p class="album-meta"></p>`;
  detail.querySelector("h2").textContent = assignment.album.title;
  detail.querySelector(".artist").textContent = assignment.album.artist_credit;
  detail.querySelector(".album-meta").textContent = [
    assignment.album.country_label,
    assignment.album.release_year,
  ].filter(Boolean).join(" · ");
  detail.append(ratingForm(assignment, project, undefined, true));
  layout.append(detail);
  parent.replaceChildren(layout);
}

function renderReveal(parent, project, { frozen = false } = {}) {
  parent.innerHTML = `
    <div class="empty-today">
      <p class="kicker">${frozen ? "Lista congelada" : "Pronto para ouvir?"}</p>
      <h2>${frozen ? "Sua lista foi congelada por inatividade." : "Seu próximo disco está esperando."}</h2>
      <p>${frozen ? "Clique abaixo para retomar a jornada a partir de hoje. Os discos já revelados continuam disponíveis no histórico." : "Mostre o primeiro álbum para iniciar a atualização diária da sua lista."}</p>
      <button class="button" type="button">Mostrar novo álbum</button>
      <p class="status" role="status"></p>
    </div>`;
  const button = parent.querySelector("button");
  button.addEventListener("click", async () => {
    button.disabled = true;
    setStatus(parent.querySelector(".status"), "Escolhendo o próximo disco…");
    try {
      const revealed = await request(`/api/v1/journeys/${encodeURIComponent(project.slug)}/today`, { method: "POST" });
      renderAlbum(parent, revealed, project);
    } catch (error) {
      setStatus(parent.querySelector(".status"), error.message, true);
      button.disabled = false;
    }
  });
}

async function renderToday(view, project) {
  try {
    const rollout = await request(`/api/v1/journeys/${encodeURIComponent(project.slug)}/today`);
    if (rollout.state === "frozen") {
      return renderReveal(view, project, { frozen: true });
    }
    if (rollout.assignment) {
      if (rollout.inactive_days > 0) return renderReveal(view, project);
      return renderAlbum(view, rollout.assignment, project);
    }
    if (rollout.state === "complete") {
      view.innerHTML = `<div class="empty-today"><p class="kicker">Jornada concluída</p><h2>Você revelou todos os discos desta lista.</h2></div>`;
      return;
    }
    renderReveal(view, project);
  } catch (error) { view.textContent = error.message; }
}

function historyItem(assignment, index, project, onSaved) {
  const item = document.createElement("article");
  item.className = "history-item";
  const position = document.createElement("div");
  position.className = "history-index";
  position.textContent = String(index).padStart(2, "0");
  const mini = miniCover(assignment.album);
  const title = document.createElement("div");
  title.className = "item-title";
  title.textContent = assignment.album.title;
  const artist = document.createElement("div");
  artist.className = "item-subtitle history-artist";
  artist.textContent = assignment.album.artist_credit;
  const date = document.createElement("time");
  date.className = "item-date";
  date.dateTime = assignment.local_date;
  date.textContent = formatDate(assignment.local_date);
  const action = assignment.rating ? document.createElement("div") : document.createElement("button");
  if (assignment.rating) {
    action.className = "item-score";
    action.textContent = String(assignment.rating.score);
  } else {
    action.type = "button";
    action.className = "history-rate-button";
    action.textContent = "Avaliar";
    action.addEventListener("click", () => {
      const existing = item.querySelector(".history-editor");
      if (existing) return existing.remove();
      const editor = document.createElement("div");
      editor.className = "history-editor";
      editor.append(ratingForm(assignment, project, onSaved));
      item.append(editor);
    });
  }
  item.append(position, mini, title, artist, date, action);
  if (assignment.rating?.review) {
    const review = document.createElement("p");
    review.className = "history-review";
    review.textContent = assignment.rating.review;
    item.append(review);
  }
  return item;
}

async function renderHistory(view, project) {
  view.innerHTML = `<div class="view-header"><div><h2>Histórico</h2><p>Os discos encontrados ao longo da sua jornada.</p></div></div><div class="history-list"></div>`;
  try {
    const history = await request(`/api/v1/journeys/${encodeURIComponent(project.slug)}/history`);
    const list = view.querySelector(".history-list");
    if (!history.length) list.innerHTML = `<p class="empty-list">Nenhum disco revelado ainda.</p>`;
    history.forEach((assignment, index) => list.append(historyItem(assignment, history.length - index, project, () => renderHistory(view, project))));
  } catch (error) { view.textContent = error.message; }
}

function catalogueItem(album) {
  const item = document.createElement("article");
  item.className = "catalogue-item";
  const rank = miniCover(album);
  const copy = document.createElement("div");
  const title = document.createElement("div");
  title.className = "item-title";
  title.textContent = album.title;
  const subtitle = document.createElement("div");
  subtitle.className = "item-subtitle";
  subtitle.textContent = album.artist_credit;
  copy.append(title, subtitle);
  const year = document.createElement("div");
  year.className = "item-date";
  year.textContent = [album.country_label, album.release_year].filter(Boolean).join(" · ") || "—";
  item.append(rank, copy, year);
  return item;
}

async function renderCatalogue(view) {
  view.innerHTML = `<div class="view-header"><div><p class="kicker">A seleção completa</p><h2>100 discos</h2><p>A seleção dos leitores da OkayAfrica, em jornadas privadas.</p></div><input class="search-input" type="search" placeholder="Buscar disco, artista ou país" aria-label="Buscar no catálogo" /></div><div class="catalogue-list"><p class="empty-list">Carregando catálogo…</p></div>`;
  try {
    const catalogue = await request("/api/v1/albums");
    const list = view.querySelector(".catalogue-list");
    const draw = (query = "") => {
      const term = query.trim().toLocaleLowerCase("pt-BR");
      const source = [...catalogue.items].sort((a, b) => a.rank - b.rank);
      const albums = term ? source.filter((album) => `${album.title} ${album.artist_credit} ${album.country_label || ""} ${album.release_year || ""}`.toLocaleLowerCase("pt-BR").includes(term)) : source;
      list.replaceChildren(...albums.map(catalogueItem));
      if (!albums.length) list.innerHTML = `<p class="empty-list">Nenhum disco encontrado.</p>`;
    };
    draw();
    view.querySelector("input").addEventListener("input", (event) => draw(event.target.value));
    appendAttribution(view, catalogue.catalogue_attribution);
  } catch (error) { view.textContent = error.message; }
}

function renderCatalogueHome() {
  document.body.classList.remove("today-page");
  document.title = "100 discos · 100 Discos Africanos";
  app.replaceChildren(header());
  const main = document.createElement("main");
  main.id = "content";
  main.className = "journey-main";
  const view = document.createElement("section");
  view.className = "view";
  main.append(view);
  app.append(main);
  renderCatalogue(view);
}

async function renderLists() {
  document.body.classList.remove("today-page");
  app.replaceChildren(header());
  const main = document.createElement("main");
  main.className = "journey-main";
  main.innerHTML = `<section class="view"><p class="kicker">Suas listas</p><h1>Continue uma lista</h1><div class="journey-links"></div></section>`;
  app.append(main);
  const links = main.querySelector(".journey-links");
  const lists = await request("/api/v1/journeys");
  if (!lists.length) links.textContent = "Nenhuma lista criada ainda.";
  lists.forEach((list) => { const a = document.createElement("a"); a.className = "journey-link"; a.href = `/${encodeURIComponent(list.slug)}`; a.textContent = list.name; links.append(a); });
}

async function renderJourney(slug, section) {
  try {
    window.scrollTo(0, 0);
    document.body.classList.toggle("today-page", section === "today");
    const project = await request(`/api/v1/journeys/${encodeURIComponent(slug)}`);
    document.title = `${project.name} · 100 Discos Africanos`;
    const frame = journeyFrame(project, section);
    app.replaceChildren(frame.fragment);
    if (section === "history") return renderHistory(frame.view, project);
    if (section === "catalogue") return renderCatalogue(frame.view);
    return renderToday(frame.view, project);
  } catch {
    document.body.classList.remove("today-page");
    document.title = "Jornada não encontrada · 100 Discos Africanos";
    app.replaceChildren(header());
    const main = document.createElement("main");
    main.className = "hero";
    main.innerHTML = `<p class="kicker">Endereço desconhecido</p><h1>Esta jornada não existe.</h1><p class="hero-copy">Confira o endereço ou crie uma nova jornada neste dispositivo.</p><p><a class="button" href="/">Voltar ao início</a></p>`;
    app.append(main);
  }
}

const legacyRoute = window.location.pathname.match(/^\/journey\/([^/]+)(?:\/(history))?\/?$/);
const cleanRoute = window.location.pathname.match(/^\/([^/]+)(?:\/(history))?\/?$/);
const route = legacyRoute || (cleanRoute && !["catalogue", "listas"].includes(cleanRoute[1]) ? cleanRoute : null);
if (route) renderJourney(decodeURIComponent(route[1]), route[2] || "today");
else if (window.location.pathname === "/catalogue") renderCatalogueHome();
else if (window.location.pathname === "/listas") renderLists();
else renderHome();
