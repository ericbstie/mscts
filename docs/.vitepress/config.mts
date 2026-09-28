import { defineConfig } from "vitepress";

const repo = "https://github.com/ericbstie/mscts";
// Served as a GitHub Pages project site, at https://ericbstie.github.io/mscts/.
const base = "/mscts/";

// https://vitepress.dev/reference/site-config
export default defineConfig({
  base,
  title: "mscts",
  description:
    "A test suite to objectively measure how closely a custom Minecraft server mimics the behavior of a vanilla Minecraft server.",
  appearance: "dark",
  cleanUrls: true,
  lastUpdated: true,
  // docs/ also holds the project's working notes. They are read on GitHub, not built.
  srcExclude: [
    "PLAN.md",
    "PROCESS.md",
    "PROGRESS.md",
    "adr/**",
    "audits/**",
    "research/**",
    "README.md",
  ],
  head: [
    ["link", { rel: "icon", type: "image/svg+xml", href: `${base}logo.svg` }],
    ["meta", { name: "theme-color", content: "#5d9e3f" }],
  ],
  markdown: {
    theme: { light: "github-light", dark: "github-dark" },
  },
  themeConfig: {
    logo: "/logo.svg",
    nav: [
      { text: "Get started", link: "/getting-started" },
      { text: "Guides", link: "/guide/how-it-works" },
      { text: "Reference", link: "/reference/cli" },
      { text: "Status", link: "/status" },
    ],
    sidebar: [
      {
        text: "Get started",
        items: [
          { text: "Getting started", link: "/getting-started" },
          { text: "How mscts works", link: "/guide/how-it-works" },
          { text: "Project status", link: "/status" },
        ],
      },
      {
        text: "Use mscts",
        items: [
          { text: "Installing servers", link: "/guide/installing-servers" },
          { text: "Running a comparison", link: "/guide/running" },
          { text: "Reading a Report", link: "/guide/reading-a-report" },
        ],
      },
      {
        text: "Extend mscts",
        items: [
          { text: "Writing an Adapter", link: "/guide/writing-an-adapter" },
          { text: "Writing a Scenario", link: "/guide/writing-a-scenario" },
        ],
      },
      {
        text: "Reference",
        items: [
          { text: "CLI", link: "/reference/cli" },
          { text: "Scenarios", link: "/reference/scenarios" },
          { text: "ServerSpec", link: "/reference/server-spec" },
          { text: "Environment variables", link: "/reference/environment" },
          { text: "Glossary", link: "/reference/glossary" },
        ],
      },
      {
        text: "Contribute",
        collapsed: true,
        items: [
          { text: "Development guide", link: "/contributing" },
          { text: "Design decisions", link: "/design-decisions" },
        ],
      },
    ],
    outline: { level: [2, 3] },
    socialLinks: [{ icon: "github", link: repo }],
    editLink: {
      pattern: `${repo}/edit/main/docs/:path`,
      text: "Edit this page on GitHub",
    },
    search: { provider: "local" },
    footer: {
      message: "Not affiliated with Mojang or Microsoft.",
    },
  },
});
