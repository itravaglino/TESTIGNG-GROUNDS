import { mkdirSync } from "node:fs";
import puppeteer from "puppeteer-core";

const out = process.argv[2] || "/tmp/forecast-qa-e2e";
mkdirSync(out, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: "/usr/bin/google-chrome-stable",
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--window-size=1400,900"],
  defaultViewport: { width: 1400, height: 900 },
});
const page = await browser.newPage();
page.setDefaultTimeout(15000);
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));

await page.goto("http://127.0.0.1:5173/", { waitUntil: "networkidle0" });
const title = await page.$eval("h1", (el) => el.textContent);
if (!title.includes("Revisión de pronósticos")) throw new Error(`Bad title: ${title}`);
await page.screenshot({ path: `${out}/01_empty.png`, fullPage: true });

const buttons = await page.$$eval("button", (els) => els.map((e) => e.textContent.trim()));
const demo = buttons.find((t) => t.includes("ejemplo"));
if (!demo) throw new Error(`No demo button. Buttons: ${buttons.join(" | ")}`);
await page.evaluate(() => {
  const b = [...document.querySelectorAll("button")].find((x) => x.textContent.includes("ejemplo"));
  b?.click();
});
await page.waitForSelector("table tbody tr");
await page.screenshot({ path: `${out}/02_dashboard.png`, fullPage: true });

const kpis = await page.$$eval(".kpi .value", (els) => els.map((e) => e.textContent.trim()));
if (kpis.length < 5) throw new Error(`Expected 5 KPIs, got ${kpis.join(",")}`);

const rowCount = async () => page.$$eval("table tbody tr", (els) => els.length);
const all = await rowCount();
await page.evaluate(() => {
  const b = [...document.querySelectorAll("button")].find((x) => x.textContent.trim() === "Descartar");
  b?.click();
});
const discarded = await rowCount();
await page.evaluate(() => {
  const b = [...document.querySelectorAll("button")].find((x) => x.textContent.trim() === "Todos");
  b?.click();
});
const restored = await rowCount();
if (discarded < 1 || discarded >= all) throw new Error(`Filter failed all=${all} discarded=${discarded}`);
if (restored !== all) throw new Error(`Todos did not restore: ${restored} vs ${all}`);

await page.click("table tbody tr");
await page.waitForSelector(".detail ul.plain");
const detail = await page.$eval(".detail", (el) => el.innerText);
await page.screenshot({ path: `${out}/03_detail.png`, fullPage: true });

await page.focus('input[type="search"]');
await page.keyboard.type("ACEITE");
await new Promise((r) => setTimeout(r, 200));
const searched = await page.$$eval("table tbody tr td:first-child", (els) => els.map((e) => e.innerText));
if (!searched.some((t) => t.includes("ACEITE"))) throw new Error(`Search failed: ${searched.join(" | ")}`);
await page.screenshot({ path: `${out}/04_search_aceite.png`, fullPage: true });

const exportDisabled = await page.$eval("button", (el) => {
  const b = [...document.querySelectorAll("button")].find((x) => x.textContent.includes("Exportar CSV"));
  return b?.disabled ?? true;
});
if (exportDisabled) throw new Error("Export CSV stayed disabled");

if (errors.length) throw new Error("Page errors: " + errors.join("\n"));

console.log(JSON.stringify({ title, kpis, all, discarded, restored, searched, detailHead: detail.slice(0, 400) }, null, 2));
await browser.close();
