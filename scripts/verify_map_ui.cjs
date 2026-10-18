const {chromium}=require('../ppt/node_modules/playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1300,height:1000}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(process.argv[2]);
    await page.locator('[data-tab="papers"]').click();
    await page.locator('#map-seed').evaluate(e=>{e.closest('details').open=true;});
    await page.locator('#map-seed').fill('https://openalex.org/W1');
    await page.getByRole('button',{name:'生成相似图 →',exact:true}).click();
    const line=page.locator('.map-stage line[data-kind="bibliometric"]');
    await line.waitFor({state:"attached"});assert.equal(await line.count(),1);assert.equal(await line.getAttribute('marker-end'),null);
    await line.focus();await page.keyboard.press('Enter');
    assert.ok((await page.locator('.map-detail').innerText()).includes('共享参考文献：1'));
    assert.ok((await page.locator('.map-detail').innerText()).includes('共同引用者：1'));
    assert.ok((await page.locator('[data-map-group="prior_works"]').innerText()).includes('W3'));
    assert.ok((await page.locator('[data-map-group="derivative_works"]').innerText()).includes('W4'));
    await page.getByLabel('相似连线依据').selectOption('coupling');assert.equal(await line.count(),1);
    await page.getByLabel('相似连线依据').selectOption('cocitation');assert.equal(await line.count(),1);
    await page.getByLabel('相似连线依据').selectOption('citations');assert.equal(await page.locator('.map-stage line').count(),0);
    await page.getByLabel('相似连线依据').selectOption('both');
    await page.locator('.map-stage g[data-paper-id="https://openalex.org/W2"]').focus();await page.keyboard.press('Enter');
    assert.ok((await page.locator('.map-detail').innerText()).includes('选中论文'));
    if(process.argv[3])await page.locator('.map-stage').screenshot({path:process.argv[3]});
    const download=page.locator('#downloads a').filter({hasText:'graph.html'});await download.waitFor();
    const offline=await browser.newPage();await offline.goto(await download.getAttribute('href'));
    await offline.locator('.map-stage line[data-kind="bibliometric"]').waitFor({state:"attached"});await offline.close();
    await page.reload();await page.locator('[data-tab="tasks"]').click();
    await page.locator('#task-list button').filter({hasText:'查看结果'}).first().click();
    await page.locator('.map-stage line[data-kind="bibliometric"]').waitFor({state:"attached"});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);
    console.log('Similarity map UI: evidence, filters, prior/derivative works, offline graph and persisted task passed');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
