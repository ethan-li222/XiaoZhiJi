"use strict";
const fs=require('node:fs');

// Runs in a fresh Chrome context, without the user's cookies or browser profile.
function arxivRows(){
  return [...document.querySelectorAll('li.arxiv-result')].map(row=>{
    const url=row.querySelector('.list-title a[href*="/abs/"]')?.href;
    const id=url?.split('/abs/')[1];if(!id)return null;
    const submitted=[...row.querySelectorAll('p')].find(p=>p.textContent.includes('Submitted'))?.textContent || '';
    const year=submitted.match(/Submitted[^;]*?(\d{4})/i)?.[1];
    const date=submitted.match(/Submitted\s+(\d{1,2}\s+\w+,?\s+\d{4})/i)?.[1];
    const timestamp=date?Date.parse(date+' UTC'):NaN;
    const abstract=(row.querySelector('.abstract-full')||row.querySelector('.abstract'))?.textContent || '';
    const claims=[...row.querySelectorAll('p')].filter(p=>/^(Comments|Journal reference):/i.test(p.textContent.trim())).map(p=>p.textContent.trim()).join(' ');
    return {id:'arxiv:'+id,title:row.querySelector('.title')?.textContent.trim()||id,
      authors:[...row.querySelectorAll('.authors a')].map(a=>a.textContent.trim()),
      year:year?Number(year):null,published_at:Number.isFinite(timestamp)?new Date(timestamp).toISOString():null,
      abstract:abstract.replace(/\s*[△▽]\s*(Less|More)\s*$/,'').trim(),
      url,arxiv_id:id,pdf_url:'https://arxiv.org/pdf/'+id,
      source_ids:{arxiv:id,browser:'arxiv'},venue_claim:claims};
  }).filter(Boolean);
}
function googleRows(){
  return [...document.querySelectorAll('.row-card__container')].map(row=>{
    const a=row.querySelector('.row-card__heading');if(!a)return null;
    const items=[...row.querySelectorAll('.row-card__subheading__item')].map(e=>e.textContent.trim());
    const year=items.at(-1)?.match(/\b(19|20)\d{2}\b/)?.[0];
    return {id:'google-research:'+new URL(a.href).pathname,title:a.textContent.trim(),url:a.href,
      authors:year?items.slice(0,-1):items,year:year?Number(year):null,
      abstract:row.querySelector('.glue-tooltip__body')?.textContent.trim()||'',
      venue:year?items.at(-1):null,venue_status:year?'indexed':'unknown',
      source_ids:{google_research:a.href,browser:'google_research'}};
  }).filter(Boolean);
}
function googleDetail(){
  const get=name=>document.querySelector(`meta[name="${name}"]`)?.content;
  const links=[...document.querySelectorAll('a[href]')];
  const pdf=get('citation_pdf_url') || links.find(a=>/\.pdf(?:$|[?#])|arxiv\.org\/pdf\//i.test(a.href))?.href;
  const abs=links.find(a=>/arxiv\.org\/abs\//.test(a.href))?.href;
  const arxiv=(pdf||abs||'').match(/arxiv\.org\/(?:pdf|abs)\/([^?#]+)/)?.[1]?.replace(/\.pdf$/,'');
  return {pdf_url:pdf||null,doi:get('citation_doi')||null,arxiv_id:arxiv||null,
    title:get('citation_title'),year:Number(get('citation_publication_date')?.match(/\d{4}/)?.[0])||null,
    authors:[...document.querySelectorAll('meta[name="citation_author"]')].map(e=>e.content)};
}
async function run(input){
  const {chromium}=require(input.playwright_path);
  const options={headless:true};if(input.chrome_path)options.executablePath=input.chrome_path;else options.channel='chrome';
  const browser=await chromium.launch(options);
  const output={papers:[],warnings:[],search_pages:[],transport:'browser'};
  const deadline=Date.now()+110000;
  try{
    const page=await browser.newPage({viewport:{width:1365,height:1000}});
    // A test may serve representative HTML locally; production URLs are built below.
    const urls=input.test_urls||{};
    const sites=input.site==='both'?['arxiv','google_research']:[input.site];
    for(const site of sites){
      const params=new URLSearchParams({query:input.query,searchtype:'all',abstracts:'show',size:'50',order:input.sort==='date'?'-announced_date_first':''});
      const url=urls[site]||(site==='arxiv'?'https://arxiv.org/search/?'+params:'https://research.google/pubs/');
      const report={site,url,status:'failed',count:0};output.search_pages.push(report);
      try{
        if(Date.now()>deadline-5000)throw new Error('浏览器检索时间预算已用尽');
        const response=await page.goto(url,{waitUntil:'domcontentloaded',timeout:Math.min(25000,deadline-Date.now())});
        if(response&&response.status()>=400)throw new Error(`页面返回 HTTP ${response.status()}`);
        const blocked=await page.evaluate(()=>/\/sorry\//.test(location.pathname)||!!document.querySelector('form[action*="captcha"],#recaptcha')||/^(Access Denied|Just a moment)/i.test(document.title));
        if(blocked)throw new Error('页面要求人工验证，请用下方来源链接在浏览器中处理');
        let rows;
        if(site==='arxiv'){
          await page.waitForFunction(()=>document.querySelector('li.arxiv-result')||/Sorry|no results|Showing 0/i.test(document.querySelector('main')?.textContent||''),{},{timeout:12000});
          rows=await page.evaluate(arxivRows);
          if(input.limit>50)output.warnings.push('arXiv 浏览器检索读取前 50 条；可缩小关键词进一步检索');
        }else{
          await page.waitForLoadState('load',{timeout:10000}).catch(()=>{});
          const search=page.locator('.search-input').filter({has:page.locator('input[type="search"]')}).last();
          const fingerprint=await page.locator('.row-card__heading').allTextContents();
          await search.locator('input[type="search"]').fill(input.query);
          // This site's search state is updated on keyup, rather than on input.
          await search.locator('input[type="search"]').press('End');
          await search.locator('button[aria-label="Submit search"]').click();
          await page.waitForFunction(previous=>JSON.stringify([...document.querySelectorAll('.row-card__heading')].map(a=>a.textContent))!==previous,
            JSON.stringify(fingerprint),{timeout:15000});
          await page.waitForLoadState('networkidle',{timeout:5000}).catch(()=>{});
          rows=(await page.evaluate(googleRows)).slice(0,input.limit);
          report.url=page.url();
          if(rows.length<input.limit)output.warnings.push('Google Research 当前读取搜索结果第一页；它仅覆盖 Google 研究团队的论文');
          for(const row of rows){
            if(input.year_from&&row.year&&row.year<input.year_from||input.year_to&&row.year&&row.year>input.year_to)continue;
            if(Date.now()>deadline-4000){output.warnings.push('部分论文详情未读取，可通过原文页查找 PDF');break;}
            try{
              await page.goto(row.url,{waitUntil:'domcontentloaded',timeout:Math.min(12000,deadline-Date.now())});
              const detail=await page.evaluate(googleDetail);
              if(detail.title)row.title=detail.title;if(detail.authors.length)row.authors=detail.authors;
              if(detail.year)row.year=detail.year;
              row.pdf_url=detail.pdf_url;row.doi=detail.doi;row.arxiv_id=detail.arxiv_id;
            }catch{output.warnings.push('部分 Google Research 论文详情读取失败，保留论文页入口');}
          }
        }
        report.count=rows.length;report.status='completed';output.papers.push(...rows.slice(0,input.limit));
      }catch(error){output.warnings.push(`${site}: ${error.message}`);report.error=error.message;}
    }
    if(input.sort==='citations')output.warnings.push('浏览器结果没有可靠的被引总数，保留来源顺序；无法按被引数排序');
    if(input.year_from||input.year_to)output.warnings.push('年份筛选应用于当前采集的结果页，未检索全站历史论文');
    return output;
  }finally{await browser.close();}
}
module.exports={arxivRows,googleRows,googleDetail,run};
if(require.main===module){let raw='';process.stdin.setEncoding('utf8');process.stdin.on('data',chunk=>raw+=chunk);process.stdin.on('end',async()=>{
  try{process.stdout.write(JSON.stringify(await run(JSON.parse(raw))));}
  catch(error){process.stderr.write(error.message);process.exitCode=1;}
});}
