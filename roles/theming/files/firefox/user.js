// Load chrome/userChrome.css (off by default since Firefox 69).
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
// Mozilla's built-in Dark theme: kept current with each Firefox release, so new
// UI surfaces get colours, unlike an old third-party static theme.
user_pref("extensions.activeThemeID", "firefox-compact-dark@mozilla.org");
user_pref("browser.theme.toolbar-theme", 0);
user_pref("browser.theme.content-theme", 0);
user_pref("layout.css.prefers-color-scheme.content-override", 0);
// about:blank and pages without their own background use this in dark mode.
user_pref("browser.display.background_color.dark", "#2E3440");
