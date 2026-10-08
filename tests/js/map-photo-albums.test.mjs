import test from 'node:test';
import assert from 'node:assert/strict';
import {albumStackMarkup, layoutMapAlbums} from '../../apps/web/client/memoir/map-photo-albums.mjs';

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

test('loading and empty albums use a labelled placeholder, never a fabricated photo', () => {
  for (const status of ['loading','empty','error']) {
    const html = albumStackMarkup({key:'city', place:'承德', label:status, status, pictures:[],count:0});
    assert.doesNotMatch(html, /<img/);
    assert.match(html, /data-photo-album="city"/);
    assert.match(html, new RegExp(`aria-label="${status}"`));
  }
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
