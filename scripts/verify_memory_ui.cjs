// Runs against an isolated test server with a deterministic model.
const {chromium} = require('../ppt/node_modules/playwright');
const assert = require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1280,height:900}});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(process.argv[2]);
    await page.locator('[data-tab="knowledge"]').click();
    await page.locator('[data-memory-view="reading"]').click();
    const card=page.locator('#knowledge-list > .record').first();
    await card.locator('summary').last().click();
    await card.locator('textarea').fill('已核对：共享参考文献。');
    await card.locator('select').selectOption('confirmed');
    await card.locator('button.primary').click();
    await page.waitForFunction(()=>document.querySelector('#knowledge-list > .record')?.dataset.memoryStatus==='confirmed');
    await page.locator('#memory-filter').selectOption('inbox');
    assert.equal(await page.locator('#knowledge-list > .record:visible').count(),0);
    await page.locator('#memory-filter').selectOption('confirmed');
    await card.locator('summary').first().click();
    assert.ok((await card.innerText()).includes('原文块'));
    await page.getByRole('button',{name:'复盘最近 7 天'}).click();
    await page.waitForFunction(()=>document.querySelector('#result pre')?.textContent.includes('pending_count'));
    await page.getByRole('button',{name:'导出 Markdown / JSON'}).click();
    await page.waitForFunction(()=>[...document.querySelectorAll('#downloads a')].some(a=>a.textContent.includes('knowledge.md')));
    const download=page.locator('#downloads a').filter({hasText:'knowledge.md'});
    assert.ok((await (await page.request.get(await download.getAttribute('href'))).text()).includes('已核对'));
    await page.reload();await page.locator('[data-tab="knowledge"]').click();await page.locator('[data-memory-view="reading"]').click();
    await page.waitForFunction(()=>document.querySelector('#knowledge-list')?.textContent.includes('已核对'));
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
    assert.deepEqual(errors,[]);
    console.log('Memory UI: edit, confirm, filter, sources, review, export, reload, mobile passed');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
