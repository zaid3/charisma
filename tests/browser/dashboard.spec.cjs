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
