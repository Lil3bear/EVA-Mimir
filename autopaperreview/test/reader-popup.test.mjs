import {test} from "node:test";
import assert from "node:assert/strict";
import {placeReaderPopup} from "../src/reader-popup.mjs";
test("reading popup follows selection and flips above near bottom",()=>{
  assert.deepEqual(placeReaderPopup({x:100,top:200,bottom:220},{width:340,height:180},{width:1000,height:800}),{left:100,top:228});
  assert.deepEqual(placeReaderPopup({x:950,top:700,bottom:720},{width:340,height:180},{width:1000,height:800}),{left:648,top:512});
});
test("reading popup stays within narrow and short viewports",()=>{
  assert.deepEqual(placeReaderPopup({x:-10,top:5,bottom:25},{width:366,height:300},{width:390,height:324}),{left:12,top:12});
});
