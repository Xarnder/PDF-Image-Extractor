import {describe,it,expect} from 'vitest';
import {toPage,normalizedBox} from './coordinates';
describe('crop coordinate mapping',()=>{
 for(const zoom of [.25,.5,1,1.5,2,4])it(`preserves PDF points at zoom ${zoom}`,()=>{
  const rect={left:37,top:89,width:600*zoom,height:800*zoom};
  const point=toPage(37+123*zoom,89+456*zoom,rect,600,800);
  expect(point[0]).toBeCloseTo(123,8);
  expect(point[1]).toBeCloseTo(456,8);
 });
 it('clamps to the page after panning',()=>expect(toPage(-20,999,{left:10,top:20,width:300,height:400},600,800)).toEqual([0,800]));
 it('normalizes a crop drawn backwards',()=>expect(normalizedBox([400,600],[20,30])).toEqual([20,30,400,600]));
});
