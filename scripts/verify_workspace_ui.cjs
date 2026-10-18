const {chromium}=require('../ppt/node_modules/playwright');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:true});try{
  const page=await browser.newPage({viewport:{width:1400,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));await page.goto(process.argv[2]);
  if(process.argv[3]){await page.locator('#login-form [name="token"]').fill(process.argv[3]);await page.locator('#login-form button').click();}
  await page.locator('[data-tab="workspace"]').click();
  await page.getByRole('button',{name:'创建第一个项目',exact:true}).waitFor();
  assert.equal(await page.locator('.desk-graph-node').count(),0);
  async function save(action,values){const form=page.locator(`[data-workspace-action="${action}"]`);await form.evaluate(f=>{ResearchDesk.reveal(f);const d=f.closest('details');if(d)d.open=true;});
    for(const [name,value] of Object.entries(values)){const input=form.locator(`[name="${name}"]`);if(await input.evaluate(e=>e.tagName==='SELECT'))await input.selectOption(value);else await input.fill(value);}
    await form.locator('button.primary').click();
  }
  await save('workspace.project.save',{name:'可靠检索研究',question:'如何提高检索可靠性',next_step:'设计可复现的对照实验'});
  await page.waitForFunction(()=>document.querySelector('#workspace-project')?.value);
  await save('workspace.import',{title:'工程阅读材料',text:'检索质量需要通过基线和实验验证。',organization:'研究笔记'});
  await page.locator('#library-list button').filter({hasText:'打开阅读与批注'}).first().click();
  await page.locator('#reader-text').getByText('检索质量需要通过基线和实验验证。',{exact:true}).waitFor();
  await save('workspace.annotation.save',{kind:'industry',selection:'检索质量需要通过基线和实验验证。',text:'先固定生成器，比较检索策略。'});
  await page.locator('#annotation-list').getByText('先固定生成器，比较检索策略。',{exact:false}).waitFor();
  await page.getByRole('button',{name:'加入对比',exact:true}).first().click();
  await page.locator('#desk-comparison').getByText('先固定生成器，比较检索策略。',{exact:false}).waitFor();
  const [comparisonDownload]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'导出对比 Markdown',exact:true}).click()]);
  assert.equal(comparisonDownload.suggestedFilename(),'research-comparison.md');
  await page.locator('#desk-search').fill('不存在的标题');
  assert.equal(await page.locator('#library-list [data-library-id]:visible').count(),0);
  await page.locator('#desk-search').fill('工程阅读');
  assert.equal(await page.locator('#library-list [data-library-id]:visible').count(),1);
  await page.locator('#desk-search').fill('');
  await save('workspace.reading.log',{minutes:'25',reflection:'明确了可验证的研究问题'});
  await page.locator('[data-desk-view="overview"]').click();
  await page.getByRole('button',{name:'综合笔记与 Idea 候选',exact:true}).click();
  try{await page.getByRole('button',{name:'采纳为 Idea 草稿',exact:true}).waitFor();}
  catch(error){console.error(JSON.stringify({errors,notice:await page.locator('#notice').textContent(),result:await page.locator('#result').textContent(),tasks:await page.evaluate(()=>fetch('/tasks').then(r=>r.json()))}));throw error;}
  await page.getByRole('button',{name:'采纳为 Idea 草稿',exact:true}).click();
  await page.locator('#idea-list').getByText('候选假设',{exact:true}).waitFor();
  await page.locator('#idea-list').getByRole('button',{name:'设计验证实验',exact:true}).click();
  await save('workspace.experiment.save',{title:'最小检索对照',baseline:'固定基线',dataset:'验证集',metrics:'准确率',controls:'固定生成器'});
  await page.locator('#experiment-list').getByText('最小检索对照',{exact:true}).waitFor();
  await page.locator('[data-desk-view="overview"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('.desk-graph-node').length===4);
  assert.equal(await page.locator('.desk-edge').count(),3);
  await page.locator('.desk-kind-2').focus();await page.keyboard.press('Enter');
  await page.locator('#desk-inspector').getByText('候选假设',{exact:true}).waitFor();
  if(process.argv[4])await page.locator('#desk-overview').screenshot({path:process.argv[4]});
  await page.keyboard.press('Control+k');
  await page.getByLabel('搜索研究记录',{exact:true}).fill('最小检索对照');
  await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');
  await page.locator('[data-workspace-action="workspace.experiment.save"] [name="title"]').evaluate(e=>{if(e.value!=='最小检索对照')throw new Error('Search did not open the experiment');});
  await page.locator('[data-desk-view="overview"]').click();
  await page.getByRole('button',{name:'生成个人工作汇报',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#deck')?.value.includes('个人工作汇报'));
  await page.waitForFunction(()=>[...document.querySelectorAll('#downloads a')].some(a=>a.textContent.includes('weekly.md')));
  assert.ok((await page.locator('#workspace-stats').innerText()).includes('25'));
  await page.reload();await page.locator('[data-tab="workspace"]').click();
  await page.locator('[data-desk-view="ideas"]').click();
  await page.locator('#idea-list').getByText('候选假设',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.locator('[data-desk-view="overview"]').click();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.deepEqual(errors,[]);console.log('Workspace UI: project, industry import, annotation, reading log, synthesis, idea, experiment, weekly report, persistence and mobile passed');
  if(process.argv[3]){await page.getByRole('button',{name:'退出工作空间',exact:true}).click();await page.locator('#login-form').waitFor();}
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
