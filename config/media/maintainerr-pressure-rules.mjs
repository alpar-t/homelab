// Run inside the Maintainerr pod: node /tmp/maintainerr-pressure-rules.mjs [--apply]
// Keep deletion rules inactive until the shared movie/TV disk is under pressure.
const base = 'http://127.0.0.1:6246';
const apply = process.argv.includes('--apply');
const groups = [
  { id: 1, name: 'Watched Movie Cleanup', app: 'radarr', appId: 1, propertyId: 23, path: '/data/media/movies', thresholdGiB: 750, cron: '0 7 * * *' },
  { id: 2, name: 'Stale Movie Cleanup', app: 'radarr', appId: 1, propertyId: 23, path: '/data/media/movies', thresholdGiB: 375, cron: '0 13 * * *' },
  { id: 3, name: 'Watched TV Cleanup', app: 'sonarr', appId: 2, propertyId: 28, path: '/data/media/tv', thresholdGiB: 750, cron: '0 7 * * *' },
  { id: 4, name: 'Stale TV Cleanup', app: 'sonarr', appId: 2, propertyId: 28, path: '/data/media/tv', thresholdGiB: 375, cron: '0 13 * * *' },
];

async function request(path, method = 'GET', body) {
  const response = await fetch(base + path, {
    method,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error(`${method} ${path}: HTTP ${response.status}`);
  return response.json();
}

const plans = [];
for (const target of groups) {
  const group = await request(`/api/rules/${target.id}`);
  if (group.name !== target.name || !group.isActive || !group.useRules || !group.collection) {
    throw new Error(`Unexpected rule group ${target.id}; inspect Maintainerr before changing it`);
  }
  const serverId = target.app === 'radarr' ? group.collection.radarrSettingsId : group.collection.sonarrSettingsId;
  if (!serverId) throw new Error(`${target.name} has no ${target.app} server`);
  const mounts = await request(`/api/servarr/${target.app}/${serverId}/diskspace`);
  const mount = mounts.find((item) => item.path === target.path);
  if (!mount || !Number.isFinite(mount.freeSpace) || mount.freeSpace <= 0) {
    throw new Error(`${target.name}: media root free space is unavailable`);
  }
  const rules = group.rules.map((record) => JSON.parse(record.ruleJson));
  const originalRules = rules.filter((rule) => !(
    rule.firstVal?.[0] === target.appId && rule.firstVal?.[1] === target.propertyId
  ));
  if (originalRules.length < 3 || originalRules.length > 4) {
    throw new Error(`${target.name}: unexpected original rule count`);
  }
  const pressureRule = {
    firstVal: [target.appId, target.propertyId],
    action: 1, // RulePossibility.SMALLER
    customVal: { ruleTypeId: 0, value: String(target.thresholdGiB) },
    operator: 0, // AND with the existing watched/stale conditions
    arrDiskPath: target.path,
    section: 0,
  };
  const payload = {
    id: group.id,
    name: group.name,
    description: group.description,
    libraryId: group.libraryId,
    isActive: group.isActive,
    arrAction: group.collection.arrAction,
    useRules: group.useRules,
    dataType: group.dataType,
    ruleHandlerCronSchedule: target.cron,
    collection: group.collection,
    listExclusions: group.collection.listExclusions,
    forceSeerr: group.collection.forceSeerr,
    radarrSettingsId: group.collection.radarrSettingsId,
    sonarrSettingsId: group.collection.sonarrSettingsId,
    notifications: group.notifications,
    rules: [...originalRules, pressureRule],
  };
  plans.push({ target, payload, freeGiB: mount.freeSpace / 1073741824 });
}

const movieFree = plans[0].freeGiB;
const tvFree = plans[2].freeGiB;
if (Math.abs(movieFree - tvFree) > 10) {
  throw new Error(`Movies and TV do not appear to share one disk (${movieFree.toFixed(1)} vs ${tvFree.toFixed(1)} GiB free)`);
}

for (const plan of plans) {
  const { target, payload, freeGiB } = plan;
  console.log(`${target.name}: ${freeGiB.toFixed(1)} GiB free; cleanup below ${target.thresholdGiB} GiB; rule ${target.cron}`);
  if (!apply) continue;
  const result = await request('/api/rules', 'PUT', payload);
  if (result.code !== 1) throw new Error(`${target.name}: Maintainerr rejected the update: ${result.result}`);
  const saved = await request(`/api/rules/${target.id}`);
  const matches = saved.rules.map((record) => JSON.parse(record.ruleJson)).filter((rule) =>
    rule.firstVal?.[0] === target.appId && rule.firstVal?.[1] === target.propertyId &&
    rule.arrDiskPath === target.path && Number(rule.customVal?.value) === target.thresholdGiB &&
    rule.action === 1 && Number(rule.operator) === 0
  );
  if (matches.length !== 1 || saved.ruleHandlerCronSchedule !== target.cron) {
    throw new Error(`${target.name}: saved rule verification failed`);
  }
}
