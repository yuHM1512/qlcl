const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const html=fs.readFileSync(path.join(__dirname,'templates/qc_input_sp.html'),'utf8');
const start=html.indexOf('    function renderOutputDisplay()');
const end=html.indexOf('    function setOutputDisplay',start);
const render=html.slice(start,end);
function check(flat, data, total, failed) {
  const elements={};
  const document={getElementById:id=>elements[id] ||= {textContent:'',className:'',classList:{add(){}}}};
  new Function('document','flatOutput','outputTotal','outputFailed','hlPassedCount','selectedTargetPercent','isCurrentPlanFlatLine','isCurrentPlanHangingLine',render+';renderOutputDisplay();')(
    document,data,total,failed,508,5,()=>flat,()=>true);
  return elements;
}
let result=check(true,{available:true,qty:508,defects:10},900,70);
assert.equal(result.lblOutputTotal.textContent,508);
assert.equal(result.lblOutputFailed.textContent,10);
assert.equal(result.lblDefectRate.textContent,'1.97%');
result=check(true,{available:false,qty:null,defects:10},900,70);
assert.equal(result.lblOutputTotal.textContent,'—');
assert.equal(result.lblDefectRate.textContent,'—');
result=check(false,null,900,10);
assert.equal(result.lblOutputTotal.textContent,518);
result=check(true,{available:true,qty:508,defects:0,records:0},900,70);
assert.equal(result.lblDefectRate.textContent,'—');
console.log('QC display: BP denominator, unknown output and hanging regression passed.');
