import test from 'node:test';
import assert from 'node:assert/strict';
import {albumStackMarkup, createMapPhotoAlbums, layoutMapAlbums} from '../../apps/web/client/memoir/map-photo-albums.mjs';

test('photo stacks show only safe embeddable images and escape place names', () => {
  const html = albumStackMarkup({key:'city', place:'承德 <script>', label:'Open photos', count:4,
    pictures:[{image_url:'https://images.example/1.jpg',allowed_actions:{embed:true}},
      {image_url:'javascript:alert(1)',allowed_actions:{embed:true}},
      {image_url:'https://images.example/private.jpg',allowed_actions:{embed:false}},
      {image_url:'/static/test.png',allowed_actions:{embed:true}}]}, 'https://memoir.test');
  assert.match(html, /承德 &lt;script&gt;/);
  assert.match(html, /images.example\/1.jpg/);
  assert.match(html, /\/static\/test.png/);
  assert.doesNotMatch(html, /javascript:|private.jpg|<script>/);
  assert.match(html, /aria-label="Open photos"/);
});

test('albums without usable photos produce no placeholder, including loading and failed searches', () => {
  for (const status of ['loading','empty','error','ready']) {
    const html = albumStackMarkup({key:'city', place:'承德', label:status, status, pictures:[],count:0});
    assert.equal(html,'');
  }
  assert.equal(albumStackMarkup({count:2,pictures:[{image_url:'javascript:alert(1)',allowed_actions:{embed:true}},
    {image_url:'https://photos.example/private.jpg',allowed_actions:{embed:false}}]}),'');
});

for (const mobile of [false,true]) test(`the ${mobile ? 'phone' : 'desktop'} photo list appears only after photos arrive`,t=>{
  const previous=globalThis.window;
  globalThis.window={location:{origin:'https://memoir.test'},addEventListener(){},matchMedia:()=>({matches:mobile})};
  t.after(()=>{if(previous===undefined) delete globalThis.window;else globalThis.window=previous;});
  const overflow={scrollTop:0};
  const layer={dataset:{},style:{},classList:{toggle(){}},querySelector:()=>overflow};
  const scene={querySelector:()=>layer};
  const empty=['loading','error','empty'].map(status=>({key:status,place:status,status,count:0,pictures:[],pinned:true}));
  let albums=empty;
  const controller=createMapPhotoAlbums({getProjectId:()=> 'project',getAlbums:()=>albums,
    getAlbum:key=>albums.find(album=>album.key===key)});
  controller.sync(scene);
  assert.equal(layer.style.display,'none');
  assert.doesNotMatch(layer.innerHTML,/data-photo-album=|data-photo-marker=|map-album-placeholder/);
  assert.equal(controller.open('loading'),false);
  albums=[...empty,{key:'found',place:'Found',count:1,pinned:true,
    pictures:[{image_url:'https://photos.example/found.jpg',allowed_actions:{embed:true}}]},
    {key:'personal',place:'Personal',count:1,pictures:[{kind:'private_upload',
      photo_id:'upload:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',allowed_actions:{embed:true}}]}];
  controller.sync(scene);
  assert.equal(layer.style.display,'');
  assert.match(layer.innerHTML,/data-photo-album="found"/);
  assert.match(layer.innerHTML,/data-photo-album="personal"/);
  assert.match(layer.innerHTML,/data-photo-marker="found"/);
  assert.doesNotMatch(layer.innerHTML,/data-photo-album="(?:loading|error|empty)"|map-album-placeholder/);
  albums=empty;
  controller.sync(scene);
  assert.equal(layer.style.display,'none');
  assert.doesNotMatch(layer.innerHTML,/data-photo-album=|data-photo-marker=/);
});

test('nearby marker albums stay distinct, inside the map and above their pins when possible', () => {
  const result = layoutMapAlbums([{key:'a',x:160,y:180},{key:'b',x:164,y:180},{key:'c',x:160,y:180}],390,300);
  assert.equal(result.length,3);
  for (const box of result) {
    assert.ok(box.left>=8 && box.top>=8 && box.left+74<=382 && box.top+74<=292);
    assert.ok(box.top+74<=180);
  }
  for (let i=0;i<result.length;i++) for (let j=i+1;j<result.length;j++) {
    const a=result[i],b=result[j];
    assert.ok(a.left+82<=b.left || b.left+82<=a.left || a.top+82<=b.top || b.top+82<=a.top);
  }
});

test('offscreen markers are omitted and crowded albums remain reachable through overflow', () => {
  const points = Array.from({length:12},(_,i)=>({key:String(i),x:80,y:90}));
  const result=layoutMapAlbums([...points,{key:'offscreen',x:-1,y:50},{key:'bad',x:NaN,y:50}],160,150);
  assert.equal(result.length,12);
  assert.ok(result.some(item=>item.overflow));
  assert.equal(new Set(result.map(item=>item.key)).size,12);
});
