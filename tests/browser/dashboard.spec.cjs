const { test, expect } = require('@playwright/test');
const token = 'browser-test-token-not-a-real-secret';
async function connect(page) {
  await page.goto('/');
  await page.getByLabel('Dashboard access token').fill(token);
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.locator('#connection')).toHaveText('Connected');
}
test('dashboard authenticates, receives reports, filters, reviews and disconnects', async ({ page, request }, info) => {
  const errors=[]; page.on('pageerror', error => errors.push(error.message));
  await request.post('/ingest', { headers: { Origin: 'http://127.0.0.1:8787', 'X-Charisma-Site-Key':'browser-fixture-key' }, data: { code:'script-error', error:'TypeError', file:'fixture.js', line:42, column:1, count:1, page:`fixture_${info.project.name}` } });
  await connect(page);
  await page.getByLabel('Search reports').fill(`fixture_${info.project.name}`);
  const card=page.locator('.event').first();
  await expect(card).toContainText('Browser script error');
  await card.getByRole('button', {name:/Mark reviewed/}).click();
  await expect(page.locator('.event').first()).toContainText('Acknowledged');
  await page.getByLabel('Review status').selectOption('open');
  await expect(page.getByText('No reports match these filters.')).toBeVisible();
  await page.getByLabel('Review status').selectOption('all');
  await page.screenshot({ path: `test-results/dashboard-${info.project.name}.png`, fullPage:true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  await page.getByRole('button', {name:'Disconnect',exact:true}).click();
  await expect(page.locator('#needs-count')).toHaveText('—');
  await expect(page.locator('.event')).toHaveCount(0);
  expect(errors).toEqual([]);
});
test('invalid token stays disconnected and supports retry', async ({page}) => {
  await page.goto('/');await page.getByLabel('Dashboard access token').fill('wrong');
  await page.getByRole('button',{name:'Connect',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('not accepted');
  await expect(page.locator('#connect-panel')).toBeVisible();
  await page.getByLabel('Dashboard access token').fill(token);
  await page.getByRole('button',{name:'Connect',exact:true}).click();
  await expect(page.locator('#connection')).toHaveText('Connected');
});
test('rendered website monitor sends a real error event without private details', async ({page,request},info) => {
  await page.goto('/');
  await page.evaluate(name => {
    const script=document.createElement('script');script.src='/monitor.js';
    script.dataset.siteKey='browser-fixture-key';script.dataset.page=`sdk_${name}`;
    document.head.append(script);
  },info.project.name);
  await page.waitForFunction(()=>Boolean(window.Charisma));
  await page.evaluate(()=>window.dispatchEvent(new ErrorEvent('error',{error:new TypeError('private-user-input'),filename:location.origin+'/bundle.js?secret=do-not-send',lineno:99,colno:2})));
  await expect.poll(async()=>{
    const response=await request.get('/api/events',{headers:{Authorization:`Bearer ${token}`}});
    const data=await response.json();return data.events.some(e=>e.page===`sdk_${info.project.name}`&&e.file==='bundle.js');
  }).toBe(true);
  const response=await request.get('/api/events',{headers:{Authorization:`Bearer ${token}`}});
  expect(await response.text()).not.toContain('private-user-input');
});
test('history expands its timeline and confirms candidate undo',async({page})=>{
  let undone=false,paused=false;
  await page.route('**/api/runs',route=>route.fulfill({json:{enabled:true,message:'Fixture worker history',runs:[{id:'aabbccddeeff0011',project:'Fixture website',commit_sha:'c'.repeat(40),status:undone?'candidate_undone':'awaiting_human_review',updated:1793040000,detail:'Fixture report',paused,can_undo:!undone,timeline:[{role:'independent_auditor',status:'approved',detail:'Focused fixture change',at:1793040000}]}]}}));
  await page.route('**/api/runs/aabbccddeeff0011/*',route=>{
    const action=route.request().url().split('/').pop();if(action==='undo')undone=true;else paused=action==='pause';
    return route.fulfill({json:{status:'ok'}});
  });
  await connect(page);
  await page.locator('#run-list summary').click();
  await expect(page.locator('#run-list')).toContainText('independent auditor: approved');
  await page.getByRole('button',{name:'Pause repairs',exact:true}).click();
  await expect(page.getByRole('button',{name:'Resume repairs',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Undo candidate',exact:true}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button',{name:'Keep candidate',exact:true}).click();
  expect(undone).toBe(false);
  await page.getByRole('button',{name:'Undo candidate',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'Undo candidate',exact:true}).click();
  await expect(page.locator('#run-list')).toContainText('candidate undone');
});
test('read access cannot edit reports or worker history',async({page})=>{
  await page.route('**/api/events',async route=>{
    const response=await route.fetch();const data=await response.json();data.can_control=false;
    await route.fulfill({json:data});
  });
  await connect(page);
  for(const button of await page.locator('.event button').all())await expect(button).toBeDisabled();
});
test('service isolation requires review and applies only the selected service',async({page})=>{
  let action=null;
  await page.route('**/api/security',route=>route.fulfill({json:{enabled:true,services:[{id:'website',auto_block:false},{id:'accounts',auto_block:false}],blocks:[],isolated:action?.action==='isolate'?[{service:'website',expires:1793043600}]:[],audit:[]}}));
  await page.route('**/api/security/control',route=>{action=route.request().postDataJSON();return route.fulfill({json:{action:action.action,service:action.service}});});
  await connect(page);
  await page.locator('summary').filter({hasText:'Manage a temporary control'}).click();
  await page.getByLabel('Action',{exact:true}).selectOption('isolate');
  await page.getByLabel('Reason',{exact:true}).fill('Investigating fixture behaviour');
  await page.getByRole('button',{name:'Review control',exact:true}).click();
  await expect(page.locator('#protection-dialog')).toBeVisible();
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  expect(action).toBeNull();
  await page.getByRole('button',{name:'Review control',exact:true}).click();
  await page.getByRole('button',{name:'Apply control',exact:true}).click();
  await expect(page.locator('#service-list')).toContainText('Isolated until');
  expect(action.service).toBe('website');expect(action.seconds).toBe(600);
  await expect(page.locator('#service-list .event').filter({hasText:'accounts'})).toContainText('Gateway access enabled');
});
