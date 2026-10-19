import {chromium} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
await fs.mkdir('artifacts/guide',{recursive:true});await fs.mkdir('output/pdf',{recursive:true});
const browser=await chromium.launch({headless:true});
try{
 const page=await browser.newPage({viewport:{width:1200,height:900}});
 await page.goto(pathToFileURL(path.resolve('public/guide/index.html')).href);
 await page.evaluate(()=>document.fonts.ready);
 assert.equal(await page.locator('img').count(),6);
 assert(await page.locator('img').evaluateAll(images=>images.every(i=>i.complete&&i.naturalWidth>0)));
 await page.screenshot({path:'artifacts/guide/desktop.png'});
 await page.pdf({path:'output/pdf/Autopaperreview-Illustrated-Guide.pdf',preferCSSPageSize:true,printBackground:true});
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:'artifacts/guide/mobile.png'});
 console.log('Six images loaded; desktop/mobile geometry checked; PDF exported');
}finally{await browser.close();}
