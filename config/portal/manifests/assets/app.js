const catalogRoot = document.querySelector("#catalog");
const emptyState = document.querySelector("#empty");
const searchInput = document.querySelector("#search");
const countLabel = document.querySelector("#service-count");
const viewPicker = document.querySelector("#view-picker");
const viewSelect = document.querySelector("#view-select");
const themeToggle = document.querySelector("#theme-toggle");
const themeLabel = document.querySelector("#theme-label");
const assetVersion = document.querySelector('meta[name="portal-asset-version"]')?.content || "local";

let catalog;
let capabilityPolicy = {};
let availableViews = [];
let currentView = "admin";

function updateThemeControl() {
  const theme = window.portalTheme?.current() || document.documentElement.dataset.theme || "dark";
  const nextTheme = theme === "dark" ? "light" : "dark";
  themeLabel.textContent = theme === "dark" ? "Dark" : "Light";
  themeToggle.setAttribute("aria-label", `Switch to ${nextTheme} mode`);
  themeToggle.title = `Switch to ${nextTheme} mode`;
}

function toggleTheme() {
  const current = window.portalTheme?.current() || document.documentElement.dataset.theme || "dark";
  const next = current === "dark" ? "light" : "dark";
  window.portalTheme?.set(next);
  updateThemeControl();
}

function makeElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function versionedAsset(path) {
  return `${path}?v=${encodeURIComponent(assetVersion)}`;
}

function serviceCard(service) {
  const policy = capabilityPolicy[service.product] || {};
  const maturity = policy.maturity;
  const baloo = policy.baloo;
  const hasSetup = Boolean(service.setup);
  const card = makeElement("article", `service-card${service.url ? "" : " info-card"}${hasSetup ? " has-setup" : ""}`);
  card.dataset.search = [
    service.name,
    service.product || "",
    service.description,
    service.auth || "",
    service.access || "",
    service.scope || "",
    maturity || "",
    baloo?.available ? "AI available" : baloo ? "AI unavailable" : "",
    baloo?.detail || "",
    ...(service.channels || []),
    ...(service.tags || []),
    ...(service.setup?.steps || []),
    ...(service.setup?.groups || []).flatMap((group) => [group.name, ...(group.agents || [])])
  ]
    .join(" ")
    .toLocaleLowerCase();

  const primary = makeElement(service.url ? "a" : "div", "service-primary");
  if (service.url) {
    primary.href = service.url;
    primary.target = "_blank";
    primary.rel = "noopener noreferrer";
  }

  const top = makeElement("div", "service-top");
  const icon = makeElement("span", "service-icon");
  icon.setAttribute("aria-hidden", "true");
  icon.style.setProperty("--accent", service.accent);
  const iconSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const iconUse = document.createElementNS("http://www.w3.org/2000/svg", "use");
  iconUse.setAttribute("href", `${versionedAsset("/icons.svg")}#${service.icon || "website"}`);
  iconSvg.append(iconUse);
  icon.append(iconSvg);
  const actions = makeElement("span", "service-actions");
  for (const channel of service.channels || []) {
    const channelIcon = makeElement("span", `channel-icon channel-${channel}`);
    const channelLabel = channel === "whatsapp" ? "Also available on WhatsApp" : `Also available on ${channel}`;
    channelIcon.setAttribute("aria-label", channelLabel);
    channelIcon.title = channelLabel;
    const channelSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    channelSvg.setAttribute("aria-hidden", "true");
    const channelUse = document.createElementNS("http://www.w3.org/2000/svg", "use");
    channelUse.setAttribute("href", `${versionedAsset("/icons.svg")}#${channel}`);
    channelSvg.append(channelUse);
    channelIcon.append(channelSvg);
    actions.append(channelIcon);
  }
  if (service.url) actions.append(makeElement("span", "open-arrow", "↗"));
  top.append(icon, actions);

  const body = makeElement("div", "service-body");
  if (service.product) body.append(makeElement("span", "service-product", service.product));
  body.append(makeElement("h3", "", service.name));
  body.append(makeElement("p", "", service.description));

  const meta = makeElement("div", "service-meta");
  if (service.scope) meta.append(makeElement("span", "scope", service.scope));
  if (maturity) {
    const maturityLabel = maturity === "experimental" ? "Experimental" : "Stable";
    meta.append(makeElement("span", `policy-badge maturity-${maturity}`, maturityLabel));
  }
  if (baloo) {
    const balooLabel = baloo.available
      ? `Baloo${baloo.detail ? ` · ${baloo.detail}` : ""}`
      : "No Baloo access";
    const balooBadge = makeElement("span", `policy-badge baloo-${baloo.available ? "available" : "unavailable"}`, balooLabel);
    balooBadge.title = baloo.available
      ? `Available through Baloo${baloo.detail ? `: ${baloo.detail}` : ""}`
      : "Baloo has no direct tool access to this service";
    meta.append(balooBadge);
  }
  if (service.network) {
    const network = makeElement("span", `network ${service.network === "home" ? "network-home" : ""}`);
    network.append(makeElement("i"), document.createTextNode(service.network === "home" ? "Home / WireGuard" : "Anywhere"));
    meta.append(network);
  }
  if (service.access) meta.append(makeElement("span", "access-badge", service.access));
  if (service.auth) meta.append(makeElement("span", "auth-badge", service.auth));

  primary.append(top, body, meta);
  card.append(primary);

  if (service.setup) {
    const details = makeElement("details", "service-setup");
    const summary = makeElement("summary");
    summary.append(
      makeElement("span", "setup-label", service.setup.label || "Setup and apps"),
      makeElement("span", "setup-chevron", "+")
    );

    const content = makeElement("div", "setup-content");
    if (service.setup.intro) content.append(makeElement("p", "setup-intro", service.setup.intro));

    if (service.setup.steps?.length) {
      const steps = makeElement("ol", "setup-steps");
      for (const step of service.setup.steps) steps.append(makeElement("li", "", step));
      content.append(steps);
    }

    for (const group of service.setup.groups || []) {
      const accessGroup = makeElement("div", "access-group");
      accessGroup.append(makeElement("strong", "", group.name));
      accessGroup.append(makeElement("p", "", group.agents.join(" · ")));
      content.append(accessGroup);
    }

    if (service.setup.links?.length) {
      const links = makeElement("div", "setup-links");
      for (const link of service.setup.links) {
        const anchor = makeElement("a", "", `${link.label} ↗`);
        anchor.href = link.url;
        anchor.target = "_blank";
        anchor.rel = "noopener noreferrer";
        links.append(anchor);
      }
      content.append(links);
    }

    details.append(summary, content);
    card.append(details);
  }

  return card;
}

function setAvailableViews(views) {
  if (!views?.length || availableViews.length) return;
  availableViews = views;
  viewSelect.replaceChildren();
  for (const view of views) {
    const option = makeElement("option", "", view.label);
    option.value = view.id;
    viewSelect.append(option);
  }
  viewPicker.hidden = false;
}

function renderCatalog(data) {
  catalogRoot.replaceChildren();
  document.querySelector("#access-label").textContent = data.label;
  document.querySelector("#intro").textContent = data.intro;
  setAvailableViews(data.views);
  if (availableViews.length) viewSelect.value = currentView;

  for (const section of data.sections) {
    const wrapper = makeElement("section", "catalog-section");
    wrapper.dataset.section = section.id;

    const heading = makeElement("div", "section-heading");
    const titleBlock = makeElement("div");
    const title = makeElement("h2", "", section.title);
    titleBlock.append(title, makeElement("p", "", section.description));
    heading.append(titleBlock, makeElement("span", "section-count", String(section.services.length)));

    const grid = makeElement("div", "service-grid");
    for (const service of section.services) grid.append(serviceCard(service));
    wrapper.append(heading, grid);
    catalogRoot.append(wrapper);
  }

  filterCatalog();
}

async function fetchCatalog(view = "") {
  const query = view ? `?view=${encodeURIComponent(view)}` : "";
  const response = await fetch(`/catalog.json${query}`, { cache: "no-store", credentials: "same-origin" });
  if (!response.ok) throw new Error(`Catalog returned ${response.status}`);
  return response.json();
}

async function fetchCapabilityPolicy() {
  const response = await fetch("/capability-policy.json", { cache: "no-store", credentials: "same-origin" });
  if (!response.ok) throw new Error(`Capability policy returned ${response.status}`);
  return response.json();
}

async function switchView(view) {
  viewSelect.disabled = true;
  try {
    const nextCatalog = await fetchCatalog(view);
    currentView = view;
    catalog = nextCatalog;
    searchInput.value = "";
    renderCatalog(catalog);
  } catch (error) {
    console.error(error);
    viewSelect.value = currentView;
  } finally {
    viewSelect.disabled = false;
  }
}

function filterCatalog() {
  if (!catalog) return;
  const query = searchInput.value.trim().toLocaleLowerCase();
  let visibleCards = 0;

  for (const section of catalogRoot.querySelectorAll(".catalog-section")) {
    let visibleInSection = 0;
    for (const card of section.querySelectorAll(".service-card")) {
      const visible = !query || card.dataset.search.includes(query);
      card.hidden = !visible;
      if (visible) visibleInSection += 1;
    }
    section.hidden = visibleInSection === 0;
    section.querySelector(".section-count").textContent = String(visibleInSection);
    visibleCards += visibleInSection;
  }

  emptyState.hidden = visibleCards !== 0;
  countLabel.textContent = `${visibleCards} capabilit${visibleCards === 1 ? "y" : "ies"}`;
}

async function loadPortal() {
  try {
    const [initialCatalog, initialPolicy, identityResponse] = await Promise.all([
      fetchCatalog(),
      fetchCapabilityPolicy(),
      fetch("/whoami", { cache: "no-store", credentials: "same-origin" })
    ]);
    capabilityPolicy = initialPolicy;
    catalog = initialCatalog;
    renderCatalog(catalog);

    if (identityResponse.ok) {
      const identity = (await identityResponse.text()).trim();
      if (identity) document.querySelector("#identity-name").textContent = identity;
    }
  } catch (error) {
    console.error(error);
    catalogRoot.replaceChildren();
    const failure = makeElement("div", "loading-card error-card");
    failure.append(makeElement("strong", "", "The portal could not load."));
    failure.append(makeElement("span", "", "Refresh the page, or check the portal deployment and authentication logs."));
    catalogRoot.append(failure);
  }
}

searchInput.addEventListener("input", filterCatalog);
viewSelect.addEventListener("change", () => switchView(viewSelect.value));
themeToggle.addEventListener("click", toggleTheme);
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && document.activeElement !== searchInput) {
    event.preventDefault();
    searchInput.focus();
  }
});

updateThemeControl();
loadPortal();
