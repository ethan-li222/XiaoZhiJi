// Read-only browser check of the running private workspace; never prints its token.
const {chromium}=require('../ppt/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://127.0.0.1:8765/');
    if(await page.locator('#login-form').count()){
      const token=fs.readFileSync(path.join(__dirname,'../data/secrets/private-access.txt'),'utf8').trim();
      await page.locator('#login-form [name="token"]').fill(token);await page.locator('#login-form button').click();
    }
    await page.locator('#desk-overview svg').waitFor();
    assert.equal(await page.locator('#workspace').getAttribute('data-view'),'overview');
    await page.keyboard.press('Control+k');await page.getByLabel('搜索研究记录',{exact:true}).waitFor();await page.keyboard.press('Escape');
    await page.locator('[data-tab="knowledge"]').click();
    await page.locator('#personal-memory').waitFor();assert.equal(await page.locator('#knowledge').getAttribute('data-memory-view'),'personal');
    await page.locator('[data-tab="reading"]').click();await page.locator('.reader-intro').waitFor();
    await page.locator('[data-tab="chat"]').click();await page.locator('.chat-main').waitFor();
    await page.locator('[data-tab="workspace"]').click();
    await page.screenshot({path:path.join(__dirname,'../data/research-desk-live.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);
    const logout=page.getByRole('button',{name:'退出工作空间',exact:true});if(await logout.isVisible()){await logout.click();await page.locator('#login-form').waitFor();}
    console.log('Live workbench: configured access, chat, personal memory, reading library, search and mobile passed');
  }finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
