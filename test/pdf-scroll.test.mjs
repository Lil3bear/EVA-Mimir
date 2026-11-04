import {test} from 'node:test';
import assert from 'node:assert/strict';
import {pageAtReadingLine} from '../src/pdf-scroll.mjs';
test('continuous PDF reading follows visible pages, including gaps and short viewports',()=>{
  const pages=[{page:1,top:20,bottom:820},{page:2,top:840,bottom:1640},{page:3,top:1660,bottom:2460}];
  assert.equal(pageAtReadingLine(pages,0,600),1);
  assert.equal(pageAtReadingLine(pages,-900,600),1);
  assert.equal(pageAtReadingLine(pages,700,600),2);
  assert.equal(pageAtReadingLine(pages,650,600),2);
  assert.equal(pageAtReadingLine(pages,1580,100),2);
  assert.equal(pageAtReadingLine([],0,600),1);
});
