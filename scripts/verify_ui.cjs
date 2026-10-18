// Explicit live UI smoke test; submits a public sample and one configured-model question.
const { chromium } = require('../ppt/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
async function main() {
  const output = path.resolve(__dirname, '../data/ui-verification');
  const skipModel = process.env.RESEARCH_UI_SKIP_MODEL === '1';
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://127.0.0.1:8765/');
    if(await page.locator('#login-form').count()){
      const token=fs.readFileSync(path.resolve(__dirname,'../data/secrets/private-access.txt'),'utf8').trim();
      await page.locator('#login-form [name="token"]').fill(token);await page.locator('#login-form button').click();
    }
    await page.waitForFunction(() => document.querySelector('#model').textContent.includes('xopglm53'));
    await page.screenshot({path: path.join(output, 'home.png'), fullPage: true});
    await page.locator('[data-tab="reading"]').click();
    await page.locator('[data-action="documents.import"] [name="title"]').fill('工作台验收示例');
    await page.locator('[data-action="documents.import"] [name="text"]').fill('# 文献耦合\n\n两篇论文引用相同的参考文献，称为文献耦合。\n\n共引是第三篇论文同时引用这两篇论文。');
    await page.locator('[data-action="documents.import"] button').click();
    await page.waitForFunction(() => document.querySelector('#documents').value !== '', { }, {timeout: 120000});
    if (!skipModel) {
    await page.locator('[name="question"]').fill('文献耦合与共引有什么区别？请根据原文解释。');
    await page.locator('[data-action="reading.ask"] button').click();
    await page.waitForFunction(() => [...document.querySelectorAll('#result h3')].some(e => e.textContent === '回答') || document.querySelector('#task-status').textContent.startsWith('失败'), {}, {timeout: 180000});
    if ((await page.locator('#task-status').textContent()).startsWith('失败')) throw new Error(await page.locator('#result').innerText());
    if (!(await page.locator('#sessions').inputValue())) throw new Error('Reading session was not selected');
    }
    await page.waitForFunction(() => document.querySelectorAll('#downloads a').length > 0);
    const artifact = await page.locator('#downloads a').first().getAttribute('href');
    const download = await page.request.get(artifact);
    if (!download.ok()) throw new Error('Artifact download failed');
    await page.screenshot({path: path.join(output, 'reading.png'), fullPage: true});
    await page.locator('[data-tab="tasks"]').click();
    if (!(await page.locator('#task-list .record').count())) throw new Error('Missing task history');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#documents').options.length > 1);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({path: path.join(output, 'mobile.png'), fullPage: true});
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    if (overflow) throw new Error('Mobile layout overflows');
    if (errors.length) throw new Error(errors.join('\n'));
    console.log(JSON.stringify({model:'xopglm53', import:true, reading:!skipModel, session:!skipModel, download:true, persistence:true, mobile:true, screenshots:output}));
  } finally { await browser.close(); }
}
main().catch(e => { console.error(e.message); process.exitCode = 1; });
