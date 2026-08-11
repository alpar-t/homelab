(() => {
  const storageKey = "newjoy-portal-theme";
  const media = window.matchMedia("(prefers-color-scheme: light)");

  function savedTheme() {
    try {
      const saved = window.localStorage.getItem(storageKey);
      return saved === "light" || saved === "dark" ? saved : null;
    } catch {
      return null;
    }
  }

  function preferredTheme() {
    return savedTheme() || (media.matches ? "light" : "dark");
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) themeColor.content = theme === "light" ? "#f4f1ea" : "#0b0f16";
  }

  function setTheme(theme) {
    try {
      window.localStorage.setItem(storageKey, theme);
    } catch {
      // The visual toggle still works when storage is unavailable.
    }
    applyTheme(theme);
  }

  applyTheme(preferredTheme());
  media.addEventListener("change", () => {
    if (!savedTheme()) applyTheme(preferredTheme());
  });

  window.portalTheme = {
    current: () => document.documentElement.dataset.theme,
    set: setTheme
  };
})();
