// factory-screenshot: capture a Lightning page in a scratch org for the pull request.
// Usage: factory-screenshot --org <alias> --path "/lightning/r/Account/<id>/view" --out .factory-out/screenshots/x.png
//        [--wait-for "c-forecast-grid"] [--width 1440] [--height 900]
// The org's login URL carries a session ID, so it is used here and never printed.
'use strict';

const { execFileSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require('playwright-core');

function args(argv) {
  const out = { width: '1440', height: '900' };
  for (let i = 0; i < argv.length; i += 2) {
    if (!argv[i].startsWith('--') || argv[i + 1] === undefined) throw new Error(`Bad argument: ${argv[i]}`);
    out[argv[i].slice(2)] = argv[i + 1];
  }
  for (const required of ['org', 'path', 'out']) {
    if (!out[required]) throw new Error(`--${required} is required`);
  }
  return out;
}

async function main() {
  const opt = args(process.argv.slice(2));
  if (!opt.path.startsWith('/')) throw new Error('--path must start with /, such as /lightning/r/Account/<id>/view');
  const allowedDir = path.resolve('.factory-out', 'screenshots');
  const out = path.resolve(opt.out);
  if (!out.startsWith(allowedDir + path.sep) || !out.endsWith('.png')) {
    throw new Error('--out must be a .png file in .factory-out/screenshots/');
  }
  fs.mkdirSync(allowedDir, { recursive: true });

  const raw = execFileSync('sf', ['org', 'open', '--target-org', opt.org, '--path', opt.path, '--url-only', '--json'],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  const url = JSON.parse(raw).result.url;

  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage({ viewport: { width: Number(opt.width), height: Number(opt.height) } });
    await page.goto(url, { waitUntil: 'load', timeout: 120000 });
    if (opt['wait-for']) {
      await page.waitForSelector(opt['wait-for'], { timeout: 60000 });
    }
    await page.waitForTimeout(5000); // Lightning keeps rendering after load
    await page.screenshot({ path: out, fullPage: true });
    console.log(`Saved ${path.relative(process.cwd(), out)}`);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(`factory-screenshot: ${err.message}`);
  process.exit(1);
});
